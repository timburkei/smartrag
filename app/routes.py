import os
import base64
import time
import uuid
from flask import request, jsonify, Response
from werkzeug.utils import secure_filename
from .utils import split_pdf_to_pages
from .pdf_processing import convert_pdf_page_to_png
from .blob_service import upload_files_to_blob, create_user_containers, initialize_blob_service, list_files_in_container, delete_file_from_blob
from .doc_intelligence import convert_pdf_page_to_md
from .ingestion_job import create_ingestion_job
from .chat_service import chat_with_data

def configure_routes(app):
    @app.route('/upload', methods=['POST'])
    def upload_file():
        if 'file' not in request.files:
            return jsonify({"error": "No file part"}), 400

        file = request.files['file']
        if file.filename == '':
            return jsonify({"error": "No selected file"}), 400

        if "___" in file.filename:
            return jsonify({"error": "File name cannot contain '___'"}), 400

        if file:
            filename = secure_filename(file.filename)
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(file_path)

            user_id = request.headers.get('X-MS-CLIENT-PRINCIPAL-NAME', "163e5568-589b-12d3-5454-426614174063")
            ingestion_container, reference_container, new_ingestion_container_created = create_user_containers(user_id)

            num_pages = split_pdf_to_pages(file_path, app.config['PROCESSED_FOLDER'], filename)
            reference_file_paths = []
            ingestion_file_paths = []

            for i in range(num_pages):
                page_pdf_path = os.path.join(app.config['PROCESSED_FOLDER'], f"{filename}___Page{i+1}.pdf")
                reference_file_paths.append(page_pdf_path)
                png_path = convert_pdf_page_to_png(page_pdf_path, i, app.config['PROCESSED_FOLDER'], filename)
                reference_file_paths.append(png_path)
                md_path = convert_pdf_page_to_md(page_pdf_path, i, app.config['PROCESSED_FOLDER'], filename)
                ingestion_file_paths.append(md_path)

            upload_files_to_blob(ingestion_container, ingestion_file_paths)
            upload_files_to_blob(reference_container, reference_file_paths)

            return jsonify({"message": "File uploaded and processed successfully", "container_name": ingestion_container}), 200

    @app.route('/list-files', methods=['GET'])
    def list_files():
        user_id = request.headers.get('X-MS-CLIENT-PRINCIPAL-NAME', "163e5568-589b-12d3-5454-426614174063")
        container_name = f"{user_id}-reference"
        try:
            file_list = list_files_in_container(container_name)
            # Extract base filenames
            base_filenames = {filename.split('___')[0] for filename in file_list}
            return jsonify({"files": list(base_filenames)}), 200
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route('/delete-file/<filename>', methods=['DELETE'])
    def delete_file(filename):
        user_id = request.headers.get('X-MS-CLIENT-PRINCIPAL-NAME', "163e5568-589b-12d3-5454-426614174063")
        container_names = [f"{user_id}-reference", f"{user_id}-ingestion"]

        try:
            for container_name in container_names:
                file_list = list_files_in_container(container_name)
                files_to_delete = [f for f in file_list if f.startswith(f"{filename}___")]
                for file in files_to_delete:
                    delete_file_from_blob(container_name, file)
            
            return jsonify({"message": f"All pages of {filename} deleted successfully from both containers"}), 200
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route('/index-files', methods=['POST'])
    def index_files():
        user_id = request.headers.get('X-MS-CLIENT-PRINCIPAL-NAME', "163e5568-589b-12d3-5454-426614174063")
        ingestion_container = f"{user_id}-ingestion"
        try:
            create_ingestion_job(ingestion_container)
            return jsonify({"message": "Indexing job created successfully"}), 200
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route('/references/<path:filename>')
    def get_source_document(filename):
        user_id = request.headers.get('X-MS-CLIENT-PRINCIPAL-NAME', "163e5568-589b-12d3-5454-426614174063")
        container_name = f"{user_id}-reference"
        blob_service_client = initialize_blob_service()
        container_client = blob_service_client.get_container_client(container_name)
        filename = filename.replace(".md", ".pdf")
        blob_client = container_client.get_blob_client(filename)
        
        try:
            blob_content = blob_client.download_blob().readall()
            blob_content_base64 = base64.b64encode(blob_content).decode('utf-8')
            return Response(blob_content_base64, content_type='text/plain')
        except Exception as e:
            print(f"Error retrieving source document: {e}")
            return "Source document not found", 404

    @app.route('/chat', methods=['POST'])
    def chat():
        user_id = request.headers.get('X-MS-CLIENT-PRINCIPAL-NAME', str(uuid.uuid4()))
        data = request.json
        return chat_with_data(data, user_id)
    
    @app.route('/stream-test', methods=['GET'])
    def stream_test():
        def generate():
            for I in range(10):
                yield f"data: Chunk {I}\n\n"
                time.sleep(1)
        return Response(generate(), content_type='text/event-stream')
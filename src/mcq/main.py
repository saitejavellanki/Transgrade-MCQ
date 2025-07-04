#!/usr/bin/env python
import sys
import os
import json
import warnings
import logging
import requests
from datetime import datetime
from flask import Flask, jsonify, request
from flask_cors import CORS

from mcq.crew import Mcq

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Suppress warnings
warnings.filterwarnings("ignore", category=SyntaxWarning, module="pysbd")

# === API Configuration ===
DJANGO_API_BASE_URL = "http://65.0.249.245:8000"
OCR_DATA_ENDPOINT = f"{DJANGO_API_BASE_URL}/ocr/"
COMPARE_TEXT_ENDPOINT = f"{DJANGO_API_BASE_URL}/compare-text/"

# -------------------------------
# 🔍 Helper Functions
# -------------------------------
def fetch_ocr_data(script_id=None):
    """
    Fetch OCR data from the Django API
    """
    try:
        params = {}
        if script_id:
            params['script_id'] = script_id
        
        response = requests.get(OCR_DATA_ENDPOINT, params=params)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.ConnectionError:
        raise Exception(f"Failed to connect to API at {DJANGO_API_BASE_URL}. Make sure the Django server is running.")
    except requests.exceptions.HTTPError as e:
        raise Exception(f"HTTP error occurred: {e}")
    except requests.exceptions.RequestException as e:
        raise Exception(f"Request error occurred: {e}")
    except json.JSONDecodeError:
        raise Exception("Invalid JSON response from API")

def extract_token_usage(crew_output):
    """
    Extract token usage information from CrewAI output
    """
    try:
        # Different ways CrewAI might store token usage
        token_usage = None
        
        # Method 1: Direct token_usage attribute
        if hasattr(crew_output, 'token_usage'):
            token_usage = crew_output.token_usage
            logger.info(f"🔥 Found token_usage attribute: {token_usage}")
        
        # Method 2: Usage metrics
        elif hasattr(crew_output, 'usage_metrics'):
            token_usage = crew_output.usage_metrics
            logger.info(f"🔥 Found usage_metrics attribute: {token_usage}")
        
        # Method 3: Check if it's in the result dictionary
        elif hasattr(crew_output, 'to_dict'):
            result_dict = crew_output.to_dict()
            if 'token_usage' in result_dict:
                token_usage = result_dict['token_usage']
                logger.info(f"🔥 Found token_usage in to_dict: {token_usage}")
            elif 'usage_metrics' in result_dict:
                token_usage = result_dict['usage_metrics']
                logger.info(f"🔥 Found usage_metrics in to_dict: {token_usage}")
        
        # Method 4: Check tasks for individual token usage
        elif hasattr(crew_output, 'tasks_output'):
            total_tokens = 0
            prompt_tokens = 0
            completion_tokens = 0
            for task_output in crew_output.tasks_output:
                if hasattr(task_output, 'token_usage'):
                    task_tokens = task_output.token_usage
                    if isinstance(task_tokens, dict):
                        total_tokens += task_tokens.get('total_tokens', 0)
                        prompt_tokens += task_tokens.get('prompt_tokens', 0)
                        completion_tokens += task_tokens.get('completion_tokens', 0)
            if total_tokens > 0:
                token_usage = {
                    'total_tokens': total_tokens,
                    'prompt_tokens': prompt_tokens,
                    'completion_tokens': completion_tokens
                }
                logger.info(f"🔥 Calculated token usage from tasks: {token_usage}")
        
        # Method 5: Check if crew has usage tracking
        elif hasattr(crew_output, 'crew') and hasattr(crew_output.crew, 'usage_metrics'):
            token_usage = crew_output.crew.usage_metrics
            logger.info(f"🔥 Found usage_metrics in crew: {token_usage}")
        
        # Method 6: Check for _usage or usage attributes
        elif hasattr(crew_output, '_usage'):
            token_usage = crew_output._usage
            logger.info(f"🔥 Found _usage attribute: {token_usage}")
        elif hasattr(crew_output, 'usage'):
            token_usage = crew_output.usage
            logger.info(f"🔥 Found usage attribute: {token_usage}")
        
        # Log detailed token usage if found
        if token_usage:
            if isinstance(token_usage, dict):
                total_tokens = token_usage.get('total_tokens', 0)
                prompt_tokens = token_usage.get('prompt_tokens', 0)
                completion_tokens = token_usage.get('completion_tokens', 0)
                logger.info(f"📊 TOKEN BREAKDOWN - Total: {total_tokens}, Prompt: {prompt_tokens}, Completion: {completion_tokens}")
            else:
                logger.info(f"📊 TOTAL TOKENS USED: {token_usage}")
        else:
            logger.warning("⚠️ No token usage information found in CrewAI output")
        
        return token_usage
        
    except Exception as e:
        logger.warning(f"Could not extract token usage: {e}")
        return None

def serialize_crew_output(crew_output):
    """
    Convert CrewOutput object to JSON-serializable format
    """
    try:
        # Extract and log token usage information
        token_usage = extract_token_usage(crew_output)
        
        if hasattr(crew_output, 'raw') and crew_output.raw:
            return crew_output.raw
        elif hasattr(crew_output, '__str__'):
            return str(crew_output)
        elif hasattr(crew_output, 'result'):
            return crew_output.result
        elif hasattr(crew_output, 'to_dict'):
            return crew_output.to_dict()
        else:
            return str(crew_output)
    except Exception as e:
        logger.warning(f"Could not serialize CrewOutput properly: {e}")
        return str(crew_output)

def save_mcq_result(script_id, mcq_result, vlmdesc=None, restructured=None, final_corrected_text=""):
    """
    Save MCQ processing result to the database via CompareText API
    """
    try:
        serialized_mcq_result = serialize_crew_output(mcq_result)
        
        data = {
            'script_id': script_id,
            'vlmdesc': vlmdesc or {},
            'restructured': restructured or {},
            'final_corrected_text': final_corrected_text,
            'mcq': serialized_mcq_result
        }
        
        logger.info(f"Saving MCQ result to database for script {script_id}...")
        
        response = requests.post(COMPARE_TEXT_ENDPOINT, 
                               json=data,
                               headers={'Content-Type': 'application/json'})
        response.raise_for_status()
        
        result = response.json()
        logger.info(f"Successfully saved to database. CompareText ID: {result.get('compare_text_id')}")
        return result
        
    except requests.exceptions.ConnectionError:
        raise Exception(f"Failed to connect to API at {DJANGO_API_BASE_URL}. Make sure the Django server is running.")
    except requests.exceptions.HTTPError as e:
        logger.error(f"HTTP error when saving to database: {e}")
        raise Exception(f"Failed to save MCQ result to database: {e}")
    except requests.exceptions.RequestException as e:
        raise Exception(f"Request error when saving to database: {e}")
    except json.JSONDecodeError:
        raise Exception("Invalid JSON response when saving to database")

def update_existing_mcq_result(compare_text_id, mcq_result):
    """
    Update existing CompareText record with MCQ result
    """
    try:
        serialized_mcq_result = serialize_crew_output(mcq_result)
        
        data = {
            'compare_text_id': compare_text_id,
            'mcq': serialized_mcq_result
        }
        
        logger.info(f"Updating existing CompareText record {compare_text_id} with MCQ result...")
        
        response = requests.put(COMPARE_TEXT_ENDPOINT, 
                              json=data,
                              headers={'Content-Type': 'application/json'})
        response.raise_for_status()
        
        result = response.json()
        logger.info(f"Successfully updated CompareText record {compare_text_id}")
        return result
        
    except requests.exceptions.HTTPError as e:
        logger.error(f"HTTP error when updating database: {e}")
        raise Exception(f"Failed to update MCQ result in database: {e}")
    except Exception as e:
        raise Exception(f"Error updating MCQ result: {e}")

def check_existing_compare_text(script_id):
    """
    Check if CompareText record already exists for the script
    """
    try:
        params = {'script_id': script_id}
        response = requests.get(COMPARE_TEXT_ENDPOINT, params=params)
        response.raise_for_status()
        
        data = response.json()
        if data and len(data) > 0:
            return data[0]
        return None
        
    except requests.exceptions.HTTPError:
        return None
    except Exception as e:
        logger.warning(f"Could not check for existing CompareText records: {e}")
        return None

def process_script_pages(script_data, script_id):
    """
    Process all pages of a script together through the MCQ crew
    """
    all_pages_ocr = []
    
    for record in script_data:
        ocr_json = record.get('ocr_json')
        if not ocr_json:
            logger.warning(f"No ocr_json found for page {record.get('page_number', 'Unknown')}")
            continue
        
        page_data = {
            'page_number': record.get('page_number'),
            'ocr_json': ocr_json
        }
        all_pages_ocr.append(page_data)
    
    if not all_pages_ocr:
        raise Exception("No valid OCR data found in any page")
    
    inputs = {
        "OCR_JSON": all_pages_ocr
    }
    
    try:
        logger.info("🚀 Processing script pages through MCQ crew...")
        result = Mcq().crew().kickoff(inputs=inputs)
        
        logger.info(f"MCQ crew result type: {type(result)}")
        
        # 🔥 EXTRACT AND LOG TOKEN USAGE
        token_usage_info = extract_token_usage(result)
        if token_usage_info:
            logger.info(f"🎯 SCRIPT {script_id} FINAL TOKEN USAGE: {token_usage_info}")
            print(f"\n{'='*60}")
            print(f"🔥 TOKEN USAGE SUMMARY FOR SCRIPT {script_id}")
            print(f"{'='*60}")
            if isinstance(token_usage_info, dict):
                print(f"📊 Total Tokens: {token_usage_info.get('total_tokens', 'N/A')}")
                print(f"📝 Prompt Tokens: {token_usage_info.get('prompt_tokens', 'N/A')}")
                print(f"✨ Completion Tokens: {token_usage_info.get('completion_tokens', 'N/A')}")
            else:
                print(f"📊 Token Usage: {token_usage_info}")
            print(f"{'='*60}\n")
        else:
            logger.warning(f"⚠️ No token usage information available for script {script_id}")
        
        try:
            existing_record = check_existing_compare_text(script_id)
            
            if existing_record:
                compare_text_id = existing_record['compare_text_id']
                db_result = update_existing_mcq_result(compare_text_id, result)
                logger.info(f"Updated existing CompareText record {compare_text_id} with MCQ result")
            else:
                db_result = save_mcq_result(
                    script_id=script_id,
                    mcq_result=result,
                    vlmdesc={"source": "MCQ processing", "pages": len(all_pages_ocr)},
                    restructured={"processed": True, "total_pages": len(all_pages_ocr)},
                    final_corrected_text=f"MCQ processing completed for {len(all_pages_ocr)} pages"
                )
                logger.info(f"Created new CompareText record with ID: {db_result.get('compare_text_id')}")
            
            return {
                'mcq_result': serialize_crew_output(result),
                'token_usage': token_usage_info,  # Include token usage in response
                'database_saved': True,
                'database_response': db_result
            }
            
        except Exception as db_error:
            logger.warning(f"MCQ processing completed but failed to save to database: {db_error}")
            return {
                'mcq_result': serialize_crew_output(result),
                'token_usage': token_usage_info,  # Include token usage in response
                'database_saved': False,
                'database_error': str(db_error)
            }
        
    except Exception as e:
        raise Exception(f"An error occurred while processing script pages: {e}")

# -------------------------------
# 🧠 Core MCQ pipeline logic
# -------------------------------
def run_mcq_pipeline(script_id):
    """
    Run the MCQ OCR Processing crew for all pages of a specific script ID together.
    """
    try:
        logger.info(f"Fetching OCR data for script ID: {script_id}")
        script_data = fetch_ocr_data(script_id=script_id)
        
        if not script_data:
            return False, f"No OCR data found for script ID: {script_id}"
        
        logger.info(f"Found {len(script_data)} pages for script ID: {script_id}")
        
        # Sort pages by page number to ensure correct order
        script_data.sort(key=lambda x: x.get('page_number', 0))
        
        # Display page information
        page_numbers = [record.get('page_number', 'Unknown') for record in script_data]
        logger.info(f"Processing pages: {page_numbers}")
        
        logger.info(f"⚡ STARTING MCQ PROCESSING for script {script_id} with {len(script_data)} pages...")
        
        try:
            result = process_script_pages(script_data, script_id)
            
            # 🔥 LOG FINAL TOKEN USAGE SUMMARY
            token_usage = result.get('token_usage')
            if token_usage:
                print(f"\n🎉 MCQ PROCESSING COMPLETED SUCCESSFULLY!")
                print(f"📋 Script ID: {script_id}")
                print(f"📄 Total Pages Processed: {len(script_data)}")
                if isinstance(token_usage, dict):
                    print(f"🔥 Total Tokens Used: {token_usage.get('total_tokens', 'N/A')}")
                else:
                    print(f"🔥 Token Usage: {token_usage}")
                print(f"💾 Database Saved: {result.get('database_saved', False)}")
            
            final_result = {
                'script_id': script_id,
                'total_pages': len(script_data),
                'pages_processed': page_numbers,
                'result': result
            }
            
            logger.info(f"✅ Successfully processed all pages for script ID: {script_id}")
            return True, final_result
            
        except Exception as e:
            logger.error(f"Error processing script pages: {e}")
            return False, f"Error processing script pages: {e}"
        
    except Exception as e:
        logger.error(f"Error processing script ID {script_id}: {e}")
        return False, f"Error processing script ID {script_id}: {e}"

# -------------------------------
# 🚀 Flask App
# -------------------------------
def run():
    app = Flask(__name__)
    app.secret_key = 'mcq_secret_key'
    
    # Enable CORS for localhost:3000
    CORS(app, origins=['http://localhost:3000'])

    @app.route('/')
    def index():
        return jsonify({
            "message": "MCQ Processing API is running",
            "usage": "Access /run/<script_id> to process a script",
            "health_check": "/health",
            "endpoints": {
                "process_script": "GET /run/<script_id>",
                "health_check": "GET /health"
            }
        })

    @app.route('/run/<int:script_id>', methods=['GET'])
    def run_pipeline_route(script_id):
        """API endpoint to run MCQ pipeline with script_id"""
        if not script_id:
            return jsonify({
                "status": "error",
                "message": "Script ID is required"
            }), 400
        
        logger.info(f"🎯 Processing MCQ pipeline for script_id: {script_id}")
        success, result = run_mcq_pipeline(script_id)
        
        if success:
            # Extract token usage for API response
            token_usage = None
            if isinstance(result, dict) and 'result' in result:
                token_usage = result['result'].get('token_usage')
            
            response_data = {
                "status": "success",
                "script_id": script_id,
                "message": f"MCQ processing completed successfully for script {script_id}",
                "data": result
            }
            
            # Add token usage to response if available
            if token_usage:
                response_data["token_usage"] = token_usage
            
            return jsonify(response_data), 200
        else:
            return jsonify({
                "status": "error",
                "script_id": script_id,
                "message": result
            }), 500

    @app.route('/run', methods=['POST'])
    def run_pipeline_post():
        """API endpoint to run MCQ pipeline with JSON payload"""
        try:
            data = request.get_json()
            if not data or 'script_id' not in data:
                return jsonify({
                    "status": "error",
                    "message": "script_id is required in JSON payload"
                }), 400
            
            script_id = data['script_id']
            logger.info(f"🎯 Processing MCQ pipeline for script_id: {script_id}")
            success, result = run_mcq_pipeline(script_id)
            
            if success:
                # Extract token usage for API response
                token_usage = None
                if isinstance(result, dict) and 'result' in result:
                    token_usage = result['result'].get('token_usage')
                
                response_data = {
                    "status": "success",
                    "script_id": script_id,
                    "message": f"MCQ processing completed successfully for script {script_id}",
                    "data": result
                }
                
                # Add token usage to response if available
                if token_usage:
                    response_data["token_usage"] = token_usage
                
                return jsonify(response_data), 200
            else:
                return jsonify({
                    "status": "error",
                    "script_id": script_id,
                    "message": result
                }), 500
                
        except Exception as e:
            logger.error(f"Error in POST endpoint: {e}")
            return jsonify({
                "status": "error",
                "message": f"Internal server error: {str(e)}"
            }), 500

    # Health check endpoint to verify Django API connectivity
    @app.route('/health')
    def health_check():
        try:
            response = requests.get(f"{DJANGO_API_BASE_URL}/ocr/", timeout=5)
            if response.status_code == 200:
                return jsonify({
                    "status": "healthy", 
                    "django_api": "connected",
                    "endpoints_available": ["ocr", "compare-text"]
                })
            else:
                return jsonify({
                    "status": "unhealthy", 
                    "django_api": "error", 
                    "details": f"Status: {response.status_code}"
                })
        except Exception as e:
            return jsonify({
                "status": "unhealthy", 
                "django_api": "disconnected", 
                "error": str(e)
            })

    # Get port from environment variable or default to 5002
    port = int(os.environ.get('PORT', 5002))
    logger.info(f"Starting MCQ API server on port {port}")
    app.run(host='0.0.0.0', port=port, debug=False)

# -------------------------------
# 🧭 Main entry
# -------------------------------
if __name__ == "__main__":
    if len(sys.argv) > 1:
        cmd = sys.argv[1].lower()
        if cmd == "run":
            run()  # 🔥 Start Flask app
        else:
            print("Invalid command. Use: run")
    else:
        print("Usage: python main.py run")
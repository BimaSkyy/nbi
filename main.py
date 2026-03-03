from flask import Flask, request, jsonify, render_template, send_from_directory
import requests
import os
import random
import string
import time
import json

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 20 * 1024 * 1024  # 20MB max

os.makedirs('uploads', exist_ok=True)


def genserial():
    return ''.join(random.choices('0123456789abcdef', k=32))


def translate_to_english(text):
    """Translate Indonesian text to English using MyMemory free API"""
    try:
        url = "https://api.mymemory.translated.net/get"
        params = {
            "q": text,
            "langpair": "id|en"
        }
        res = requests.get(url, params=params, timeout=10)
        data = res.json()
        translated = data["responseData"]["translatedText"]
        # If translation fails or returns same text with error
        if data["responseStatus"] == 200:
            return translated
        return text
    except Exception as e:
        print(f"Translation failed: {e}")
        return text  # fallback to original


def upimage(filename):
    form_data = {'file_name': filename}
    headers = {
        'origin': 'https://imgupscaler.ai',
        'referer': 'https://imgupscaler.ai/'
    }
    res = requests.post(
        'https://api.imgupscaler.ai/api/common/upload/upload-image',
        data=form_data,
        headers=headers
    )
    res.raise_for_status()
    return res.json()['result']


def upload_to_oss(put_url, file_path):
    ext = os.path.splitext(file_path)[1].lower()
    content_type = 'image/png' if ext == '.png' else 'image/jpeg'
    with open(file_path, 'rb') as f:
        file_data = f.read()
    res = requests.put(
        put_url,
        data=file_data,
        headers={
            'Content-Type': content_type,
            'Content-Length': str(len(file_data))
        }
    )
    return res.status_code == 200


def create_job(image_url, prompt):
    headers = {
        'product-code': 'magiceraser',
        'product-serial': genserial(),
        'origin': 'https://imgupscaler.ai',
        'referer': 'https://imgupscaler.ai/'
    }
    form_data = {
        'model_name': 'magiceraser_v4',
        'original_image_url': image_url,
        'prompt': prompt,
        'ratio': 'match_input_image',
        'output_format': 'jpg'
    }
    res = requests.post(
        'https://api.magiceraser.org/api/magiceraser/v2/image-editor/create-job',
        data=form_data,
        headers=headers
    )
    res.raise_for_status()
    return res.json()['result']['job_id']


def check_job(job_id):
    headers = {
        'origin': 'https://imgupscaler.ai',
        'referer': 'https://imgupscaler.ai/'
    }
    res = requests.get(
        f'https://api.magiceraser.org/api/magiceraser/v1/ai-remove/get-job/{job_id}',
        headers=headers
    )
    res.raise_for_status()
    return res.json()


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/translate', methods=['POST'])
def translate():
    data = request.json
    text = data.get('text', '')
    translated = translate_to_english(text)
    return jsonify({'translated': translated})


@app.route('/edit', methods=['POST'])
def edit():
    try:
        # Get uploaded file
        if 'image' not in request.files:
            return jsonify({'error': 'No image uploaded'}), 400
        
        file = request.files['image']
        prompt = request.form.get('prompt', '')
        
        if not prompt:
            return jsonify({'error': 'Prompt kosong'}), 400

        # Save uploaded file
        ext = os.path.splitext(file.filename)[1] or '.jpg'
        filename = f"upload_{int(time.time())}{ext}"
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(file_path)

        # Step 1: Get upload URL
        upload_info = upimage(filename)
        
        # Step 2: Upload to OSS
        upload_to_oss(upload_info['url'], file_path)

        # Step 3: Get CDN URL
        cdn_url = 'https://cdn.imgupscaler.ai/' + upload_info['object_name']

        # Step 4: Create job
        job_id = create_job(cdn_url, prompt)

        # Step 5: Poll for result
        max_attempts = 30
        for _ in range(max_attempts):
            time.sleep(3)
            result = check_job(job_id)
            if result.get('code') != 300006:
                break

        if result.get('result') and result['result'].get('output_url'):
            output_url = result['result']['output_url'][0]
            return jsonify({
                'success': True,
                'output_url': output_url,
                'job_id': job_id
            })
        else:
            return jsonify({'error': 'Gagal memproses gambar'}), 500

    except Exception as e:
        print(f"Error: {e}")
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)

from flask import Flask, render_template, request, redirect, url_for, flash, send_from_directory
import uuid
from werkzeug.utils import secure_filename
import os 

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'user_uploads')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg'}

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.secret_key = 'vidsnapai_secret_key_development'  # Required for session flashing
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


@app.route("/user_uploads/<path:filename>")
def serve_upload(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)


@app.route("/")
def home():
    return render_template("index.html")

@app.route("/create", methods=["GET", "POST"])
def create():
    myid = uuid.uuid1()
    if request.method == "POST":
        rec_id = request.form.get("uuid")
        desc = request.form.get("text")
        input_files = []
        if not rec_id:
            rec_id = str(uuid.uuid1())
        upload_dir = os.path.join(app.config['UPLOAD_FOLDER'], rec_id)
        os.makedirs(upload_dir, exist_ok=True)

        uploaded_files = request.files.getlist('files[]')
        for file in uploaded_files:
            if file and file.filename:
                filename = secure_filename(file.filename)
                if not allowed_file(filename):
                    continue
                file.save(os.path.join(upload_dir, filename))
                input_files.append(filename)

        if not input_files:
            flash("Error: Please upload at least one valid image file (PNG, JPG, JPEG).", "danger")
            return redirect(url_for('create'))

        with open(os.path.join(upload_dir, "desc.txt"), "w") as f:
            f.write(desc or "")

        with open(os.path.join(upload_dir, "input.txt"), "w") as f:
            for fl in input_files:
                f.write(f"file '{fl}'\n")
                f.write("duration 1\n")

        flash("Reel generation started! Your video will appear in the gallery within a few seconds.", "success")
        return redirect(url_for('gallery'))

    return render_template("create.html", myid=myid)

@app.route("/gallery")
def gallery():
    reels_dir = os.path.join(BASE_DIR, 'static', 'reels')
    reels = []
    if os.path.exists(reels_dir):
        # Scan reels directory and sort by last modified time (newest first)
        files = [f for f in os.listdir(reels_dir) if f.endswith(".mp4")]
        files.sort(key=lambda x: os.path.getmtime(os.path.join(reels_dir, x)), reverse=True)
        
        for filename in files:
            reel_id = filename.rsplit('.', 1)[0]
            
            # Read description
            desc = ""
            desc_path = os.path.join(app.config['UPLOAD_FOLDER'], reel_id, 'desc.txt')
            if os.path.exists(desc_path):
                with open(desc_path, 'r', encoding='utf-8') as f:
                    desc = f.read().strip()
            
            # Find the first image to use as thumbnail
            thumbnail = ""
            upload_dir = os.path.join(app.config['UPLOAD_FOLDER'], reel_id)
            if os.path.exists(upload_dir):
                image_files = [
                    img for img in sorted(os.listdir(upload_dir))
                    if img.lower().endswith(('.png', '.jpg', '.jpeg'))
                ]
                if image_files:
                    thumbnail = url_for('serve_upload', filename=f"{reel_id}/{image_files[0]}")
            
            reels.append({
                "id": reel_id,
                "video_url": url_for('static', filename=f"reels/{filename}"),
                "thumbnail_url": thumbnail or url_for('static', filename='1.jpg'),
                "title": desc[:30] + "..." if len(desc) > 30 else (desc or "Untitled Reel"),
                "description": desc
            })
            
    return render_template("gallery.html", reels=reels)

if __name__ == "__main__":
    import subprocess
    import sys
    import atexit
    
    worker_process = None
    
    # Start the worker only once (avoiding the double-start in Flask debug reloader)
    if not app.debug or os.environ.get('WERKZEUG_RUN_MAIN') == 'true':
        worker_path = os.path.join(BASE_DIR, "generate_process.py")
        print(f"[*] Starting background generator: {worker_path}")
        worker_process = subprocess.Popen([sys.executable, worker_path])
        
    def cleanup_worker():
        global worker_process
        if worker_process and worker_process.poll() is None:
            print("[*] Stopping background generator...")
            worker_process.terminate()
            try:
                worker_process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                worker_process.kill()
            print("[*] Background generator stopped.")
            worker_process = None

    atexit.register(cleanup_worker)

    try:
        app.run(debug=True)
    finally:
        cleanup_worker()
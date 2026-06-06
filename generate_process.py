# This file looks for new folders inside user_uploads and convert them into reels if they are not already converted 
import os 
from text_to_audio import text_to_speech_file
import time
import subprocess
import json
from PIL import Image, ImageFilter

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
USER_UPLOADS_DIR = os.path.join(BASE_DIR, "user_uploads")
REELS_DIR = os.path.join(BASE_DIR, "static", "reels")
DONE_FILE = os.path.join(BASE_DIR, "done.txt")


def preprocess_image(input_path, output_path):
    """Resizes and pads an image to 1080x1920 with a blurred background version of itself."""
    img = Image.open(input_path)
    target_w, target_h = 1080, 1920
    
    img_aspect = img.width / img.height
    target_aspect = target_w / target_h
    
    # 1. Background image: resize to fill 1080x1920 and apply heavy blur
    if img_aspect > target_aspect:
        bg_h = target_h
        bg_w = int(target_h * img_aspect)
    else:
        bg_w = target_w
        bg_h = int(target_w / img_aspect)
        
    bg = img.resize((bg_w, bg_h), Image.Resampling.LANCZOS)
    # Crop to center
    left = (bg_w - target_w) // 2
    top = (bg_h - target_h) // 2
    bg = bg.crop((left, top, left + target_w, top + target_h))
    # Apply Gaussian Blur
    bg = bg.filter(ImageFilter.GaussianBlur(30))
    
    # 2. Foreground image: resize to fit within 1080x1920
    if img_aspect > target_aspect:
        fg_w = target_w
        fg_h = int(target_w / img_aspect)
    else:
        fg_h = target_h
        fg_w = int(target_h * img_aspect)
        
    fg = img.resize((fg_w, fg_h), Image.Resampling.LANCZOS)
    
    # Paste centered
    paste_x = (target_w - fg_w) // 2
    paste_y = (target_h - fg_h) // 2
    bg.paste(fg, (paste_x, paste_y))
    
    # Save as JPEG
    bg.convert("RGB").save(output_path, "JPEG", quality=90)


def get_audio_duration(audio_path):
    """Probes the exact duration of the audio file using ffprobe."""
    command = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        audio_path
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=True)
    return float(result.stdout.strip())


def text_to_audio(folder):
    print("TTA -", folder)
    desc_file = os.path.join(USER_UPLOADS_DIR, folder, "desc.txt")
    with open(desc_file) as f:
        text = f.read().strip()
    
    # Fallback text if empty
    if not text:
        text = "VidSnap AI Reel"
        
    print(f"Generating voiceover: '{text}' for folder {folder}")
    text_to_speech_file(text, folder)


def create_reel(folder):
    folder_path = os.path.join(USER_UPLOADS_DIR, folder)
    audio_mp3 = os.path.join(folder_path, "audio.mp3")
    
    # 1. Find all uploaded images (exclude preprocessed ones)
    all_files = sorted(os.listdir(folder_path))
    image_files = []
    for f in all_files:
        ext = f.rsplit('.', 1)[-1].lower() if '.' in f else ''
        if ext in {'png', 'jpg', 'jpeg'} and not f.startswith('proc_'):
            image_files.append(f)
            
    if not image_files:
        raise ValueError("No images found in upload folder to process.")
        
    # 2. Preprocess all images to uniform 1080x1920 size with blurred margins
    proc_files = []
    for idx, img_name in enumerate(image_files):
        in_path = os.path.join(folder_path, img_name)
        out_name = f"proc_{idx}.jpg"
        out_path = os.path.join(folder_path, out_name)
        preprocess_image(in_path, out_path)
        proc_files.append(out_name)
        
    # 3. Calculate slide durations based on generated audio length
    audio_duration = 5.0  # Fallback duration
    if os.path.exists(audio_mp3):
        try:
            audio_duration = get_audio_duration(audio_mp3)
            print(f"Audio duration probed: {audio_duration} seconds")
        except Exception as e:
            print(f"Failed to probe audio duration, using fallback: {e}")
            
    num_images = len(proc_files)
    duration_per_image = audio_duration / num_images
    
    # 4. Generate dynamic input.txt for ffmpeg
    input_txt = os.path.join(folder_path, "input.txt")
    with open(input_txt, "w") as f:
        for proc_file in proc_files:
            f.write(f"file '{proc_file}'\n")
            f.write(f"duration {duration_per_image:.3f}\n")
        # To fix the last frame bug in ffmpeg concat demuxer, repeat the last image at the end
        if proc_files:
            f.write(f"file '{proc_files[-1]}'\n")
            
    # 5. Run ffmpeg command (using preprocessed JPEGs)
    output_mp4 = os.path.join(REELS_DIR, f"{folder}.mp4")
    command = f'''ffmpeg -y -f concat -safe 0 -i "{input_txt}" -i "{audio_mp3}" -vf "scale=1080:1920" -c:v libx264 -c:a aac -shortest -r 30 -pix_fmt yuv420p "{output_mp4}"'''
    print(f"Running ffmpeg: {command}")
    subprocess.run(command, shell=True, check=True)
    print("CR  -", folder)

if __name__ == "__main__":
    os.makedirs(REELS_DIR, exist_ok=True)
    open(DONE_FILE, "a").close()

    while True:
        print("Processing queue...")
        with open(DONE_FILE, "r") as f:
            done_folders = {line.strip() for line in f}

        if not os.path.exists(USER_UPLOADS_DIR):
            os.makedirs(USER_UPLOADS_DIR, exist_ok=True)
            
        folders = [
            name for name in os.listdir(USER_UPLOADS_DIR)
            if os.path.isdir(os.path.join(USER_UPLOADS_DIR, name))
        ]

        for folder in folders:
            if folder in done_folders:
                continue

            input_txt = os.path.join(USER_UPLOADS_DIR, folder, "input.txt")
            desc_txt = os.path.join(USER_UPLOADS_DIR, folder, "desc.txt")

            if not (os.path.exists(input_txt) and os.path.exists(desc_txt)):
                print("Skipping incomplete folder:", folder)
                continue

            # Check if there are any images in the folder
            folder_path = os.path.join(USER_UPLOADS_DIR, folder)
            try:
                image_files = [
                    f for f in os.listdir(folder_path)
                    if f.rsplit('.', 1)[-1].lower() in {'png', 'jpg', 'jpeg'} and not f.startswith('proc_')
                ]
            except Exception as e:
                print(f"Error reading folder {folder}: {e}")
                continue

            if not image_files:
                print("Skipping folder with no images:", folder)
                with open(DONE_FILE, "a") as f:
                    f.write(folder + "\n")
                continue

            try:
                text_to_audio(folder)
                create_reel(folder)
            except Exception as e:
                print("Failed processing", folder, e)
                # Write to done.txt to avoid infinite loop calling ElevenLabs API
                with open(DONE_FILE, "a") as f:
                    f.write(folder + "\n")
                continue

            with open(DONE_FILE, "a") as f:
                f.write(folder + "\n")
        time.sleep(4)
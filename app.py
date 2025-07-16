import os
import json
import shutil
import subprocess
import tempfile

from flask import Flask, request, redirect, render_template, url_for, flash, jsonify, send_file
from models import db, Song
from werkzeug.utils import secure_filename
from datetime import datetime
import sqlite3
from markupsafe import Markup
import re
from sqlalchemy import case
from pathlib import Path
from generate_tex import generate_latex_content

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///songs.db'
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.secret_key = 'your-secret-key-here'
ALLOWED_EXTENSIONS = {'mp3', 'pdf', 'midi', 'mid', 'tex', 'mscz'}
JSON_FOLDER = 'songs'
BACKUP_FOLDER = 'instance/backups'

db.init_app(app)

# Ensure upload and backup folders exist
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(BACKUP_FOLDER, exist_ok=True)
os.makedirs(JSON_FOLDER, exist_ok=True)

# Helper functions
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_song_upload_folder(song_id):
    """Create song-specific upload folder path"""
    song_folder = os.path.join(app.config['UPLOAD_FOLDER'], str(song_id))
    os.makedirs(song_folder, exist_ok=True)
    return song_folder

def backup_db(src_path, backup_folder):
    """Create database backup"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = os.path.join(backup_folder, f'backup_{timestamp}.db')
    
    src = sqlite3.connect(src_path)
    dest = sqlite3.connect(backup_path)
    with dest:
        src.backup(dest)
    dest.close()
    src.close()
    return backup_path

def delete_song_files(song_id):
    """Delete all files associated with a song"""
    song_folder = os.path.join(app.config['UPLOAD_FOLDER'], str(song_id))
    if os.path.exists(song_folder):
        shutil.rmtree(song_folder)

# Routes

@app.route('/song/<int:song_id>/generate_tex', methods=['POST'])
def generate_tex(song_id):
    song = Song.query.get_or_404(song_id)

    # Get save folder
    folder = get_song_upload_folder(song.id)
    os.makedirs(folder, exist_ok=True)

    # Determine filename
    tex_filename = f"{secure_filename(song.song_id or song.title)}.tex"
    tex_path = os.path.join(folder, tex_filename)

    # Prepare LaTeX content
    latex = generate_latex_content(song)

    # Write to .tex file
    with open(tex_path, 'w', encoding='utf-8') as f:
        f.write(latex)

    # Save path in DB
    song.tex_path = tex_path
    db.session.commit()

    flash("TeX file generated successfully.")
    return redirect(url_for('index'))


@app.route('/')
def index():
    songs = Song.query.order_by(Song.song_id).all()
    return render_template('index.html', songs=songs)

@app.route('/load_songs')
def load_songs():
    for fname in os.listdir(JSON_FOLDER):
        if fname.endswith(".json"):
            with open(os.path.join(JSON_FOLDER, fname), 'r', encoding='utf-8') as f:
                data = json.load(f)
                if not Song.query.filter_by(title=data['title']).first():
                    song = Song(
                        title=data.get('title'),
                        author=data.get('author') if data.get('author') is not None and len(data.get('author')) > 1 else None,
                        categories=",".join(data.get('categories', [])),
                        song_parts=json.dumps(data["song_parts"], ensure_ascii=False),
                        checked=False,
                        admin_checked=False
                    )
                    db.session.add(song)
    db.session.commit()
    flash("Songs loaded.")
    return redirect(url_for('index'))

@app.route('/backup')
def backup():
    backup_path = backup_db(os.path.abspath('instance/songs.db'), BACKUP_FOLDER)
    flash(f"Backup created: {backup_path}")
    return redirect(url_for('index'))

@app.route('/delete_file/<int:song_id>/<file_type>', methods=['POST'])
def delete_file(song_id, file_type):
    song = Song.query.get_or_404(song_id)
    song_folder = get_song_upload_folder(song_id)

    if file_type == 'tex':
        if song.tex_path and os.path.exists(song.tex_path):
            os.remove(song.tex_path)
            song.tex_path = None

            if song.pdf_lyrics_path and os.path.exists(song.pdf_lyrics_path):
                os.remove(song.pdf_lyrics_path)
                song.pdf_lyrics_path = None

            if song.pdf_lyrics_path and os.path.exists(song.pdf_lyrics_path):
                os.remove(song.pdf_lyrics_path)
                song.pdf_chords_path = None

    elif file_type == 'pdf_lyrics':
        if song.pdf_lyrics_path and os.path.exists(song.pdf_lyrics_path):
            os.remove(song.pdf_lyrics_path)
        song.pdf_lyrics_path = None
    elif file_type == 'pdf_chords':
        if song.pdf_lyrics_path and os.path.exists(song.pdf_lyrics_path):
            os.remove(song.pdf_lyrics_path)
        song.pdf_chords_path = None
    elif file_type in ['mp3', 'midi', 'sheet_pdfs', 'sheet_mscz']:
        path_to_delete = request.form.get('path')
        
        # Determine which attribute to update based on file type
        attr_mapping = {
            'mp3': 'mp3_paths',
            'midi': 'midi_paths',
            'sheet_pdfs': 'sheet_pdf_paths',  # Assuming you have this attribute
            'sheet_mscz': 'sheet_mscz_paths'              # Assuming you have this attribute
        }
        
        attr = attr_mapping[file_type]
        paths = json.loads(getattr(song, attr) or '[]')
        
        if path_to_delete in paths:
            paths.remove(path_to_delete)
            if os.path.exists(path_to_delete):
                os.remove(path_to_delete)
            setattr(song, attr, json.dumps(paths, ensure_ascii=False))

    db.session.commit()
    flash(f"{file_type.upper()} file deleted.")
    return redirect(url_for('song_detail', song_id=song.id))

@app.route('/song/add', methods=['GET', 'POST'])
def add_song():
    if request.method == 'POST':
        song = Song(
            title=request.form['title'],
            version_name=request.form['version_name'],

            author=request.form['author'] if request.form['author'] is not None and len(request.form['author']) > 1 else None,
            title_original=request.form.get('title_original', ''),
            author_original=request.form.get('author_original', ''),
            checked='checked' in request.form,
            admin_checked='admin_checked' in request.form,

            categories=';;'.join(request.form.get('categories', '').split(',')),
            alternative_titles=';;'.join(request.form.getlist('alternative_titles'))
        )

        # Handle song parts
        parts = []
        idx = 0
        while True:
            part_type = request.form.get(f'part_type_{idx}')
            part_lines = request.form.get(f'part_lines_{idx}')
            if part_type and part_lines:
                parts.append({
                    'type': part_type,
                    'lines': [line.strip() for line in part_lines.splitlines() if line.strip()]
                })
                idx += 1
            else:
                break
        song.song_parts = json.dumps(parts, ensure_ascii=False)

        db.session.add(song)
        db.session.commit()  # Commit to get song ID
        
        song_folder = get_song_upload_folder(song.id)

        # Handle file uploads
        def handle_file_upload(file, field_name):
            if file and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                path = os.path.join(song_folder, filename)
                file.save(path)
                return path
            return None

        # Single files
        song.tex_path = handle_file_upload(request.files.get('tex'), 'tex')
        song.pdf_lyrics_path = handle_file_upload(request.files.get('pdf_lyrics'), 'pdf_lyrics')
        song.pdf_chords_path = handle_file_upload(request.files.get('pdf_chords'), 'pdf_chords')

        # Multiple files
        def handle_multi_upload(files, field_name):
            paths = []
            for file in files:
                if file and allowed_file(file.filename):
                    filename = secure_filename(file.filename)
                    path = os.path.join(song_folder, filename)
                    file.save(path)
                    paths.append(path)
            return json.dumps(paths, ensure_ascii=False)

        song.mp3_paths = handle_multi_upload(request.files.getlist('mp3s'), 'mp3s')
        song.midi_paths = handle_multi_upload(request.files.getlist('midis'), 'midis')
        song.sheet_pdf_paths = handle_multi_upload(request.files.getlist('sheet_pdfs'), 'sheet_pdfs')
        song.sheet_mscz_paths = handle_multi_upload(request.files.getlist('sheet_msczs'), 'sheet_mscz')


        db.session.commit()
        flash("Song added successfully!")
        return redirect(url_for('index'))

    return render_template('song_detail.html', song=Song(), data=[], mp3s=[], midis=[], is_edit=False)

@app.route('/song/<int:song_id>', methods=['GET', 'POST'])
def song_detail(song_id):
    song = Song.query.get_or_404(song_id)
    
    if request.method == 'POST':
        # Handle song association
        
        song.title = request.form['title']
        song.author = request.form['author'] if request.form['author'] is not None and len(request.form['author']) > 1 else None
        song.version_name = request.form['version_name']

        song.title_original = request.form.get('title_original', '')
        song.author_original = request.form.get('author_original', '')
        song.checked = 'checked' in request.form
        song.admin_checked = 'admin_checked' in request.form

        song.categories = ';;'.join(request.form.get('categories', '').split(','))
        song.alternative_titles = ';;'.join(request.form.getlist('alternative_titles'))

        # Update song parts
        parts = []
        idx = 0
        while True:
            part_type = request.form.get(f'part_type_{idx}')
            part_lines = request.form.get(f'part_lines_{idx}')
            if part_type and part_lines:
                parts.append({
                    'type': part_type,
                    'lines': [line.strip() for line in part_lines.splitlines() if line.strip()]
                })
                idx += 1
            else:
                break
        song.song_parts = json.dumps(parts, ensure_ascii=False)

        song_folder = get_song_upload_folder(song.id)

        # Handle file uploads
        def handle_file_update(current_path, file, field_name):
            if file and allowed_file(file.filename):
                # Delete old file if exists
                if current_path and os.path.exists(current_path):
                    os.remove(current_path)
                # Save new file
                filename = secure_filename(file.filename)
                path = os.path.join(song_folder, filename)
                file.save(path)
                return path
            return current_path

        # Update single files
        song.tex_path = handle_file_update(song.tex_path, request.files.get('tex'), 'tex')
        song.pdf_lyrics_path = handle_file_update(song.pdf_lyrics_path, request.files.get('pdf_lyrics'), 'pdf_lyrics')
        song.pdf_chords_path = handle_file_update(song.pdf_chords_path, request.files.get('pdf_chords'), 'pdf_chords')

        # Update multiple files
        def update_multi_files(current_paths, new_files, field_name):
            paths = json.loads(current_paths or '[]')
            
            # Handle deletions
            paths = [p for p in paths if os.path.exists(p)]  # Remove any deleted files
            
            # Add new files
            for file in new_files:
                if file and allowed_file(file.filename):
                    filename = secure_filename(file.filename)
                    path = os.path.join(song_folder, filename)
                    file.save(path)
                    paths.append(path)
            
            return json.dumps(paths, ensure_ascii=False)

        song.mp3_paths = update_multi_files(song.mp3_paths, request.files.getlist('mp3s'), 'mp3s')
        song.midi_paths = update_multi_files(song.midi_paths, request.files.getlist('midis'), 'midis')
        song.sheet_pdf_paths = update_multi_files(song.sheet_pdf_paths, request.files.getlist('sheet_pdfs'), 'sheet_pdfs')
        song.sheet_mscz_paths = update_multi_files(song.sheet_mscz_paths, request.files.getlist('sheet_mscz'), 'sheet_mscz')

        if 'associated_song_id' in request.form:
            associated_song_id = request.form['associated_song_id']
            associated_song = Song.query.filter_by(song_id=associated_song_id).first()
            
            if associated_song:
                try:
                    # Store original titles
                    associated_original_title = associated_song.title
                    
                    # Get the NEW title from the form submission
                    new_title = request.form['title']
                    
                    # Update BOTH songs
                    song.title = new_title                   # Set common title
                    song.version_name = song.version_name  # Preserve original as version
                    
                    associated_song.title = new_title           # Set common title
                    associated_song.version_name = associated_original_title  # Preserve original
                    print(song.song_id)
                    song.song_id = associated_song.song_id  # Associate IDs
                    print(song.song_id)
                    db.session.commit()
                    flash(f"Songs successfully associated with common title: {new_title}", 'success')
                    return redirect(url_for('index'))

                
                except Exception as e:
                    db.session.rollback()
                    flash(f"Error during association: {str(e)}", 'error')
                    return redirect(url_for('song_detail', song_id=song.id))
            
            flash("Associated song not found", 'error')
            return redirect(url_for('index'))
        
        db.session.commit()
        flash("Song updated successfully!")
        return redirect(url_for('index'))

    # Prepare data for template
    song.alternative_titles = song.alternative_titles.split(';;') if song.alternative_titles else []
    data = json.loads(song.song_parts) if song.song_parts else []
    mp3s = json.loads(song.mp3_paths or '[]')
    midis = json.loads(song.midi_paths or '[]')
    sheet_pdfs = json.loads(song.sheet_pdf_paths or '[]')
    sheet_mscz = json.loads(song.sheet_mscz_paths or '[]')
    
    return render_template('song_detail.html', song=song, data=data, mp3s=mp3s, midis=midis, sheet_pdfs=sheet_pdfs, sheet_mscz=sheet_mscz, is_edit=True)

@app.route('/song/delete/<int:song_id>', methods=['POST'])
def delete_song(song_id):
    song = Song.query.get_or_404(song_id)
    delete_song_files(song_id)
    db.session.delete(song)
    db.session.commit()
    flash("Song deleted successfully!")
    return redirect(url_for('index'))

# Template filter for chord rendering
@app.template_filter('replace_chords')
def replace_chords_filter(text):
    return Markup(re.sub(r"\[([^\]]+)\]", r"<sup style='color:orange; font-size:1.1em'><strong>\1</strong></sup>", text))

@app.route('/api/songs')
def get_songs():
    prefix = request.args.get('prefix', '').upper()
    exclude_id = request.args.get('exclude_id')  # song_id to exclude
    print(exclude_id)
    # Base query parts
    matching = (
        db.session.query(Song.song_id, Song.title)
        .filter(Song.song_id.startswith(prefix))
    )
    
    others = (
        db.session.query(Song.song_id, Song.title)
        .filter(~Song.song_id.startswith(prefix))
    )
    
    if exclude_id:
        matching = matching.filter(Song.song_id != exclude_id)
        others = others.filter(Song.song_id != exclude_id)

    combined_query = matching.union(others)

    combined = combined_query.order_by(
        case(
            (Song.song_id.startswith(prefix), 0),
            else_=1
        ),
        Song.song_id,
        Song.title
    ).all()

    return jsonify([{'song_id': sid, 'title': title} for sid, title in combined])


@app.route('/generate_pdfs/<int:song_id>')
def generate_pdfs(song_id):
    song = Song.query.get_or_404(song_id)

    if not song.tex_path or not os.path.exists(song.tex_path):
        flash("TeX file not found for this song.", "error")
        return redirect(url_for('song_detail', song_id=song_id))

    song_folder = get_song_upload_folder(song.id)
    tex_file = song.tex_path
    basename = os.path.splitext(os.path.basename(tex_file))[0]

    pdf_lyrics_path = os.path.join(song_folder, 'lyrics.pdf')
    pdf_chords_path = os.path.join(song_folder, 'lyrics_chords.pdf')

    def run_latex(tex_path, set_chords_bool, output_filename):
        with open(tex_path, 'r', encoding='utf-8') as f:
            tex_content = f.read()

        # Replace \setboolean{showchords}
        replacement = r'\\setboolean{showchords}{' + ('True' if set_chords_bool else 'False') + '}'
        tex_content = re.sub(r'\\setboolean\{showchords\}\{.*?\}', replacement, tex_content)

        # Create absolute path to fonts
        fonts_src = os.path.abspath('static/fonts')
        
        with tempfile.TemporaryDirectory() as tmpdir:
            # Copy preamble
            shutil.copy("preamble.tex", tmpdir)
            
            # Create fonts directory structure in temp dir
            fonts_dest = os.path.join(tmpdir, 'fonts')
            os.makedirs(fonts_dest, exist_ok=True)
            
            # Copy all font files
            for font_file in os.listdir(fonts_src):
                if font_file.endswith(('.ttf', '.otf')):
                    shutil.copy(os.path.join(fonts_src, font_file), fonts_dest)

            # Update font path in tex content to use absolute path
            tex_content = tex_content.replace(
                'Path=./fonts/',
                f'Path={fonts_dest}/'
            )

            tmp_tex_path = os.path.join(tmpdir, "song.tex")
            with open(tmp_tex_path, "w", encoding='utf-8') as f:
                f.write(tex_content)

            try:
                for _ in range(2):
                    result = subprocess.run(
                        ["lualatex", "-interaction=nonstopmode", "song.tex"],
                        cwd=tmpdir,
                        check=True,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE
                    )
                print(result.stdout.decode())
            except subprocess.CalledProcessError as e:
                print("STDOUT:\n", e.stdout.decode(errors='ignore'))
                print("STDERR:\n", e.stderr.decode(errors='ignore'))
                raise RuntimeError("LaTeX compilation failed")

            # Copy result to final path
            generated_pdf = os.path.join(tmpdir, "song.pdf")
            os.makedirs(os.path.dirname(output_filename), exist_ok=True)
            shutil.copyfile(generated_pdf, output_filename)

    run_latex(tex_file, set_chords_bool=False, output_filename=pdf_lyrics_path)
    run_latex(tex_file, set_chords_bool=True, output_filename=pdf_chords_path)

    # Update DB
    song.pdf_lyrics_path = pdf_lyrics_path
    song.pdf_chords_path = pdf_chords_path
    db.session.commit()

    flash("PDFs generated successfully.", "success")
    return redirect(url_for('song_detail', song_id=song_id))

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)
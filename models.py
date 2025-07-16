from flask_sqlalchemy import SQLAlchemy
from flask import Flask, render_template, request, send_file, redirect, url_for, current_app
from flask_sqlalchemy import SQLAlchemy
import os
import json
import subprocess
from tempfile import mkdtemp
from shutil import rmtree, copy2
from sqlalchemy import event
from pathlib import Path
from unidecode import unidecode
import re
import os
from sqlalchemy import UniqueConstraint

db = SQLAlchemy()

class Song(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    song_id = db.Column(db.String(10), nullable=False)  # Format: A-001
    version_name = db.Column(db.String(100), nullable=True)
    title = db.Column(db.String, nullable=False)
    author = db.Column(db.String, nullable=True)
    title_original = db.Column(db.String, nullable=True)
    author_original = db.Column(db.String, nullable=True)
    categories = db.Column(db.String, nullable=True)
    # Store alternative titles as comma-separated string
    alternative_titles = db.Column(db.String, nullable=True)
    song_parts = db.Column(db.Text, nullable=False)
    checked = db.Column(db.Boolean, default=False)
    admin_checked = db.Column(db.Boolean, default=False)

    pdf_lyrics_path = db.Column(db.String(200))
    pdf_chords_path = db.Column(db.String(200))
    tex_path = db.Column(db.String(200))

    midi_paths = db.Column(db.Text)  # stored as JSON list
    mp3_paths = db.Column(db.Text)
    sheet_pdf_paths = db.Column(db.Text)
    sheet_mscz_paths = db.Column(db.Text)


    
    __table_args__ = (
        UniqueConstraint('song_id', 'version_name', name='uix_song_id_version'),
    )
from sqlalchemy import event
from sqlalchemy.orm import Session
import json

def generate_song_id(mapper, connection, target):
    session = Session.object_session(target)
    with session.no_autoflush:
        normalized_title = unidecode(target.title).strip()
        if not normalized_title:
            raise ValueError("Title is required to generate song_id")
        
        letter = normalized_title[0].upper()

        # Get all existing song_ids from DB
        all_ids = session.query(Song.song_id).all()
        pattern = re.compile(f"^{re.escape(letter)}-\\d{{3}}$")

        # Filter and parse IDs that match the pattern
        existing_ids = [sid[0] for sid in all_ids if sid[0] and pattern.match(sid[0])]

        used_numbers = sorted([
            int(match.group(1))
            for sid in existing_ids
            if (match := re.search(r'-(\d{3})$', sid))
        ])

        # Find first available number
        new_number = 1
        for num in used_numbers:
            if num == new_number:
                new_number += 1
            else:
                break

        # Assign unique song_id
        target.song_id = f"{letter}-{new_number:03d}"
    
def handle_song_update(mapper, connection, target):
    session = Session.object_session(target)
    state = db.inspect(target)
    
    if 'title' in state.attrs and state.attrs.title.history.has_changes():
        old_title = state.attrs.title.history.deleted[0]
        new_title = target.title
        
        # Normalize and compare initial letters
        old_initial = unidecode(old_title.strip())[0].upper() if old_title else ''
        new_initial = unidecode(new_title.strip())[0].upper() if new_title else ''
        
        # Only regenerate if initial letter changed
        if old_initial != new_initial:
            generate_song_id(mapper, connection, target)
        # If letter stayed the same but title changed, keep existing song_id
        
event.listen(Song, 'before_insert', generate_song_id)
event.listen(Song, 'before_update', handle_song_update)


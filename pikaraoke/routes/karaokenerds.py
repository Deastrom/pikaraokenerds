import json
import os
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_paginate import Pagination, get_page_parameter
from pikaraoke.lib.current_app import get_karaoke_instance
import flask_babel
import threading
from pikaraoke.lib.karaokenerds import scrape

_ = flask_babel.gettext

karaokenerds_bp = Blueprint('karaokenerds', __name__)

@karaokenerds_bp.route("/karaokenerds", methods=["GET", "POST"])
def karaokenerds():
    k = get_karaoke_instance()
    search = False
    q = request.args.get("q")
    if q:
        search = True
    page = request.args.get(get_page_parameter(), type=int, default=1)

    available_songs = k.karaokenerds_songs  # Directly use the list of songs

    letter = request.args.get("letter", "all")
    search_string = request.args.get("search_string")
    sort_order = request.args.get("sort", "title")

    if search_string:
        search_terms = search_string.lower().split()
        available_songs = [
            song for song in available_songs
            if all(term in f'{song["Title"]} {song["Artist"]} {song["Brand"]}'.lower() for term in search_terms)
        ]

    if letter and letter != "all":
        result = []
        if letter == "numeric":
            for song in available_songs:
                if song['Title'][0].isnumeric():
                    result.append(song)
        else:
            for song in available_songs:
                if sort_order == "artist" and song['Artist'].lower().startswith(letter.lower()):
                    result.append(song)
                elif sort_order == "brand" and song['Brand'].lower().startswith(letter.lower()):
                    result.append(song)
                elif sort_order == "title" and song['Title'].lower().startswith(letter.lower()):
                    result.append(song)
        available_songs = result

    if sort_order == "artist":
        songs = sorted(available_songs, key=lambda x: x['Artist'])
    elif sort_order == "brand":
        songs = sorted(available_songs, key=lambda x: x['Brand'])
    else:
        songs = sorted(available_songs, key=lambda x: x['Title'])

    results_per_page = 20
    pagination = Pagination(
        css_framework="bulma",
        page=page,
        total=len(songs),
        search=search,
        record_name="songs",
        per_page=results_per_page,
    )
    start_index = (page - 1) * results_per_page
    end_index = start_index + results_per_page
    songs = songs[start_index:end_index]

    return render_template(
        "karaokenerds.html",
        songs=songs,
        pagination=pagination,
        letter=letter,
        sort_order=sort_order,
        search_string=search_string,
    )

@karaokenerds_bp.route("/karaokenerds/download", methods=["POST"])
def download():
    k = get_karaoke_instance()
    d = request.form.to_dict()
    song = d["song-url"]
    user = d["song-added-by"]
    title = d["song-title"]
    queue = True

    # download in the background since this can take a few minutes
    t = threading.Thread(target=k.download_video, args=[song, queue, user, title])
    t.daemon = True
    t.start()

    displayed_title = title if title else song
    flash_message = (
        _("Download started: %s. This may take a couple of minutes to complete.")
        % displayed_title
    )

    flash_message += _("Song will be added to queue by %s.") % user
    flash(flash_message, "is-info")
    return redirect(url_for("karaokenerds.karaokenerds"))
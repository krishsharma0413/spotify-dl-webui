from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from dotenv import dotenv_values
from pydantic import BaseModel
import shutil
import os
from typing import Union
import spotipy
import multiprocessing as mp
from concurrent.futures import ProcessPoolExecutor
import asyncio
from spotipy.oauth2 import SpotifyClientCredentials
from spotify_dl.spotify import (
    fetch_tracks,
    parse_spotify_url,
    validate_spotify_urls,
    get_item_name,
)
from spotify_dl.youtube import (
    download_songs,
    default_filename,
    find_and_download_songs
)
from pathlib import Path, PurePath


app = FastAPI()

sp_data = dotenv_values("cred.env")
client_id = sp_data["CLIENTID"]
client_secret = sp_data["CLIENTSECRET"]

thanks_message = "Thank you ♥️"
url_error_message = "URL provided is Invalid. The URL should start with <span class='text-gray-400'>https://open.spotify.com/</span>"

templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")

class ProcessingURL(BaseModel):
    url: str


@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/songs/{filename}", response_class=Union[FileResponse, HTMLResponse])
async def song(request: Request, filename: str):
    try:
        if Path(f"./songs/{filename}").exists():
            return FileResponse(f"./songs/{filename}")
        else:
            return templates.TemplateResponse("thankyou.html", {"request": request, "message": "File not found"}, status_code=404)
    except:
            return templates.TemplateResponse("thankyou.html", {"request": request, "message": "File not found"}, status_code=404)


def validator(url):
    
    try:
        valid_urls = validate_spotify_urls([url])
        if not valid_urls:
            # await websocket.send_text(url_error_message)
            return
    except:
        # await websocket.send_text(url_error_message)
        return

    return valid_urls

def total_checker(valid_urls, random):
    sp = spotipy.Spotify(
        auth_manager=SpotifyClientCredentials(
            client_id=client_id, client_secret=client_secret
        )
    )

    url_data = {"urls": []}
    url = valid_urls[0]
    url_dict = {}
    item_type, item_id = parse_spotify_url(url)
    directory_name = get_item_name(sp, item_type, item_id)
    url_dict["save_path"] = Path(
        PurePath.joinpath(Path("./songs/"), f"[{random}] {Path(directory_name)}", Path(directory_name))
    )
    url_dict["save_path"].mkdir(parents=True, exist_ok=True)
    url_dict["songs"] = fetch_tracks(sp, item_type, item_id)
    url_data["urls"].append(url_dict.copy())

    total_number_of_music = len(url_dict['songs'])

    return  total_number_of_music, url_data, directory_name

def downloader(url_data, random, directory_name):
    
    kwargs = download_songs(
        songs=url_data,
        output_dir=".",
        format_str="bestaudio/best",
        skip_mp3=False,
        keep_playlist_order=False,
        no_overwrites=False,
        remove_trailing_tracks="no",
        use_sponsorblock="no",
        file_name_f=default_filename,
        multi_core=0,
        proxy="",
        random=random,
    )
    return kwargs

loop = asyncio.get_event_loop()
loop.set_default_executor(ProcessPoolExecutor())

@app.websocket("/processing/{random}")
async def processor(*, websocket: WebSocket, random:str):
    await websocket.accept()
    data = await websocket.receive_text()
    url = data
    await websocket.send_text("Processing...")
    
    valid_urls = await loop.run_in_executor(None, validator, url)
    total_songs, url_data, directory_name  = await loop.run_in_executor(None, total_checker, valid_urls, random)

    await websocket.send_text(f"Total Songs: {total_songs}")

    kwargs = await loop.run_in_executor(None, downloader, url_data, random, directory_name)
    
    await websocket.send_text("Starting Download...")

    sponsorblock_postprocessor = []
    reference_file = kwargs["reference_file"]
    files = {}

    with open(reference_file, "r", encoding="utf-8") as file:
        for line in file:
            temp = line.split(";")
            name, artist, album, i = (
                temp[0],
                temp[1],
                temp[4],
                int(temp[-1].replace("\n", "")),
            )
            await loop.run_in_executor(None, find_and_download_songs, kwargs, name, artist, album, i, temp, sponsorblock_postprocessor, reference_file, files)
            await websocket.send_text("+1")

    os.remove(random + ".log")
    shutil.make_archive(f"./songs/[{random}] {directory_name}", "zip", f"./songs/[{random}] {directory_name}")
    shutil.rmtree(PurePath.joinpath(Path("./songs/"), f"[{random}] {Path(directory_name)}"))

    await websocket.send_text(f"completed: /songs/[{random}] {directory_name}.zip")
    await websocket.send_text(thanks_message)
    return

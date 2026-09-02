# YouTube Downloader

Eenvoudige Windows desktopapp voor het downloaden van video's en playlists met **Nederlandse gesproken audio**.

## Kernflow

1. Plak een video- of playlistlink.
2. Kies een uitvoermap.
3. Klik eerst op **Download testvideo**.
4. De app controleert of een Nederlandse audiotrack beschikbaar is.
5. Speel de testvideo af vanuit de uitvoermap.
6. Als de taal en kwaliteit goed zijn, klik je op **Download hele playlist**.

## Belangrijk

De app downloadt geen ondertiteling. Er wordt bewust alleen een expliciet als Nederlands gemarkeerde audiotrack geaccepteerd. Als YouTube geen Nederlandse taalmetadata aanbiedt, stopt de app in plaats van automatisch een andere taal te kiezen.

## Starten op Windows

Dubbelklik op `run.bat`. De benodigde Python-pakketten worden automatisch geïnstalleerd en daarna start de app.

## Vereisten

Python 3.10 of nieuwer.

FFmpeg wordt via `imageio-ffmpeg` meegeleverd, dus een losse FFmpeg-installatie is normaal niet nodig.

"""Gemensam filhantering för bilagor.

Filer sparas som {root}/{key}/{uuid}{ändelse} på uploads-volymen. Originalnamnet
lever bara i databasen – dels för att två kunder kan ladda upp "offert.pdf", dels
för att ett namn från en uppladdning aldrig ska kunna styra var på disken något
hamnar.
"""
import os
import uuid


def store_file(root: str, key, original_name: str, content: bytes) -> str:
    """Skriver innehållet och returnerar det genererade filnamnet på disk."""
    ext = os.path.splitext(original_name or "")[1].lower()
    stored_name = f"{uuid.uuid4()}{ext}"
    folder = os.path.join(root, str(key))
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, stored_name), "wb") as f:
        f.write(content)
    return stored_name


def file_path(root: str, key, stored_name: str) -> str:
    return os.path.join(root, str(key), stored_name)


def remove_file(root: str, key, stored_name: str) -> None:
    """Tar bort filen om den finns. Att den redan är borta är inget fel – posten
    i databasen ska kunna städas bort ändå."""
    path = file_path(root, key, stored_name)
    if os.path.exists(path):
        os.remove(path)


def copy_file(src_root: str, src_key, dest_root: str, dest_key, stored_name: str) -> str:
    """Kopierar en redan lagrad fil till ett annat objekt och returnerar det nya
    filnamnet. Används när en offert blir arbetsorder – bilagorna ska följa med
    utan att originalet försvinner om offerten sedan raderas."""
    src = file_path(src_root, src_key, stored_name)
    if not os.path.exists(src):
        return ""
    ext = os.path.splitext(stored_name)[1].lower()
    new_name = f"{uuid.uuid4()}{ext}"
    folder = os.path.join(dest_root, str(dest_key))
    os.makedirs(folder, exist_ok=True)
    with open(src, "rb") as fsrc, open(os.path.join(folder, new_name), "wb") as fdst:
        fdst.write(fsrc.read())
    return new_name

# utils/branch_tracking.py
from pathlib import Path


def get_known_branches(data_dir: Path, chain_id: str, folder_name: str):
    """
    Branches that have EVER had a file of this type
    (e.g. folder_name='prices' or 'pricesfull').
    Scanned from the local filesystem, since it reflects
    what the API has actually returned in the past.
    """
    branches = set()

    for folder in data_dir.glob(f"{chain_id}/*/*/{folder_name}"):
        _, subchain, store = folder.parts[-4:-1]
        branches.add((subchain, store))

    return branches


def find_silent_branches(known_branches, updated_branches):
    """
    Branches with a history of this file type that
    didn't get a new one this run.
    """
    return known_branches - updated_branches
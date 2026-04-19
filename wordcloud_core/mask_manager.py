import os
from typing import Optional

import numpy as np
from PIL import Image

from .config import Config


class MaskManager:
    def __init__(self, config: Config):
        self._config = config

    def get_mask(self, group_key: Optional[str] = None) -> Optional[np.ndarray]:
        if group_key:
            group_mask = os.path.join(self._config.mask_dir, f"mask-{group_key}.png")
            if os.path.isfile(group_mask):
                return self._load_mask(group_mask)

        default_mask = os.path.join(self._config.mask_dir, "default.png")
        if os.path.isfile(default_mask):
            return self._load_mask(default_mask)

        return None

    def save_mask(self, image_data: bytes, group_key: Optional[str] = None) -> str:
        import io
        filename = f"mask-{group_key}.png" if group_key else "default.png"
        path = os.path.join(self._config.mask_dir, filename)

        img = Image.open(io.BytesIO(image_data))
        img = img.convert("RGBA")
        img.save(path, "PNG")
        return path

    def delete_mask(self, group_key: Optional[str] = None) -> bool:
        filename = f"mask-{group_key}.png" if group_key else "default.png"
        path = os.path.join(self._config.mask_dir, filename)
        if os.path.isfile(path):
            os.remove(path)
            return True
        return False

    def _load_mask(self, path: str) -> Optional[np.ndarray]:
        try:
            img = Image.open(path)
            if img.mode != "RGBA":
                img = img.convert("RGBA")
            return np.array(img)
        except Exception:
            return None

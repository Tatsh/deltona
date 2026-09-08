"""Repair a progressive web app's icons in a profile."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING

from niquests import AsyncSession

from deltona.typing import assert_not_none

if TYPE_CHECKING:
    from types import ModuleType

    from deltona.typing import StrPath

__all__ = ('fix_chromium_pwa_icon',)


def _get_pil_image_module() -> ModuleType:  # pragma: no cover
    from PIL import Image  # ruff:ignore[import-outside-top-level]

    return Image


async def fix_chromium_pwa_icon(config_path: StrPath,
                                app_id: str,
                                icon_src_uri: str,
                                profile: str = 'Default',
                                *,
                                masked: bool = False,
                                monochrome: bool = False) -> None:
    """
    Fix a Chromium PWA icon that failed to sync.

    Parameters
    ----------
    config_path : StrPath
        Path to the Chromium configuration directory.
    app_id : str
        App ID of the PWA.
    icon_src_uri : str
        URI of the icon source.
    profile : str
        Profile name. Default is ``'Default'``.
    masked : bool
        If ``True``, save the icon as a maskable icon. Default is ``False``.
    monochrome : bool
        If ``True``, save the icon as a monochrome icon. Default is ``False``.

    Raises
    ------
    ValueError
        If the icon is not square.

    See Also
    --------
    `Bug 40595456 - PWA icons can be lost (on sync?) and reverted to a letter`_
    """
    image_mod = _get_pil_image_module()
    config_path = Path(config_path) / profile / 'Web Applications' / app_id
    async with AsyncSession() as session:
        r = await session.get(icon_src_uri, timeout=15)
    r.raise_for_status()
    content = assert_not_none(r.content)
    img = image_mod.open(BytesIO(content))
    width, height = img.size
    if width != height:
        msg = 'Icon is not square.'
        raise ValueError(msg)
    sizes = list(reversed([1 << x for x in range(4, min(10, width.bit_length()))]))
    for size in sizes:
        img.resize((size, size), image_mod.LANCZOS).save(config_path / 'Icons' / f'{size}.png')
    if masked:
        for size in sizes:
            img.resize((size, size),
                       image_mod.LANCZOS).save(config_path / 'Icons Maskable' / f'{size}.png')
    if monochrome:
        for size in sizes:
            img.resize((size, size),
                       image_mod.LANCZOS).save(config_path / 'Icons Monochrome' / f'{size}.png')

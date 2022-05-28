from typing import Tuple
import logging


def parse_rect64(data: str) -> Tuple[float, float, float, float]:  # left, top, right, bottom
    """https://gist.github.com/fbuchinger/1073823#file-picasa-ini-L147-L160"""
    # Strip the rect64() from the outside.
    assert data.startswith("rect64(") and data.endswith(")"), input
    data = data[7:-1]
    #logging.info("data=%s" % data)
    assert len(data) >= 1
    data = data.zfill(16)  # Zeros in front, as Picasa abbreviates.
    # noinspection PyTypeChecker
    return tuple(parse_hexfloat(data[start:(start + 4)]) for start in range(0, 16, 4))


def parse_hexfloat(data: str) -> float:
    """https://gist.github.com/fbuchinger/1073823#file-picasa-ini-L162-L169"""
    return int(data, 16) / 65536


def to_digikam_rect(image_size: Tuple[int, int, int], rect: Tuple[float, float, float, float]) -> str:
    """Creates the XML for digiKam's ImageTagProperties.value column."""
    width, height, orientation = image_size
    left, top, right, bottom = rect

    # Apply the orientation. For the meaining of the orientation values, see here:
    # https://github.com/KDE/digikam/blob/33d0457e20adda97c003f3dee652a1749406ff9f/core/libs/metadataengine/engine/metaengine.h#L95-L103
    if orientation == 0 or orientation == 1:  # No orientation
        x1 = left
        x2 = right
        y1 = top
        y2 = bottom
    elif orientation == 3:  # 180º rotation
        x1 = 1 - right
        x2 = 1 - left
        y1 = 1 - bottom
        y2 = 1 - top
    elif orientation == 6:  # 90º rotation (clock-wise)
        height, width = width, height
        x1 = 1 - bottom
        x2 = 1 - top
        y1 = left
        y2 = right
    elif orientation == 8:  # 270º rotation (clock-wise)
        height, width = width, height
        x1 = top
        x2 = bottom
        y1 = 1 - right
        y2 = 1 - left
    else:
        raise ValueError('Unsupported orientation %s' % orientation)

    return '<rect x="{:d}" y="{:d}" width="{:d}" height="{:d}"/>'.format(
        int(width * x1),
        int(height * y1),
        int(width * (x2 - x1)),
        int(height * (y2 - y1)),
    )

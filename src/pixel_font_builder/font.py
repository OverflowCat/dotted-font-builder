from pixel_font_builder.glyph import Glyph
from pixel_font_builder.info import MetaInfos


class FontBuilder:
    def __init__(
            self,
            size: int,
            ascent: int,
            descent: int,
            x_height: int,
            cap_height: int,
            character_mapping: dict[int, str] = None,
            glyphs: list[Glyph] = None,
            meta_infos: MetaInfos = None,
    ):
        self.size = size
        self.ascent = ascent
        self.descent = descent
        self.x_height = x_height
        self.cap_height = cap_height
        self.character_mapping = character_mapping
        self.glyphs = glyphs
        self.meta_infos = meta_infos
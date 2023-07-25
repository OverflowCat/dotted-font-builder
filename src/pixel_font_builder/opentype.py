import logging
from enum import StrEnum

from fontTools.fontBuilder import FontBuilder
from fontTools.misc.psCharStrings import T2CharString as OTFGlyph
from fontTools.pens.t2CharStringPen import T2CharStringPen as OTFGlyphPen
from fontTools.pens.ttGlyphPen import TTGlyphPen as TTFGlyphPen
from fontTools.ttLib import TTCollection
from fontTools.ttLib.tables._g_l_y_f import Glyph as TTFGlyph

from pixel_font_builder import font
from pixel_font_builder.glyph import Glyph
from pixel_font_builder.info import MetaInfos

logger = logging.getLogger('pixel_font_builder.opentype')

_CACHE_NAME_TAG = '_opentype_cache_tag'
_CACHE_NAME_OUTLINES = '_opentype_cache_outlines'
_CACHE_NAME_OTF_GLYPH = '_opentype_cache_otf_glyph'
_CACHE_NAME_TTF_GLYPH = '_opentype_cache_ttf_glyph'


class Configs:
    def __init__(
            self,
            px_to_units: int = 100,
    ):
        self.px_to_units = px_to_units


class Flavor(StrEnum):
    WOFF = 'woff'
    WOFF2 = 'woff2'


def _create_name_strings(meta_infos: MetaInfos) -> dict[str, str]:
    """
    https://learn.microsoft.com/en-us/typography/opentype/spec/name#name-ids
    copyright (nameID 0)
    familyName (nameID 1)
    styleName (nameID 2)
    uniqueFontIdentifier (nameID 3)
    fullName (nameID 4)
    version (nameID 5)
    psName (nameID 6)
    trademark (nameID 7)
    manufacturer (nameID 8)
    designer (nameID 9)
    description (nameID 10)
    vendorURL (nameID 11)
    designerURL (nameID 12)
    licenseDescription (nameID 13)
    licenseInfoURL (nameID 14)
    typographicFamily (nameID 16)
    typographicSubfamily (nameID 17)
    compatibleFullName (nameID 18)
    sampleText (nameID 19)
    postScriptCIDFindfontName (nameID 20)
    wwsFamilyName (nameID 21)
    wwsSubfamilyName (nameID 22)
    lightBackgroundPalette (nameID 23)
    darkBackgroundPalette (nameID 24)
    variationsPostScriptNamePrefix (nameID 25)
    """
    unique_name = meta_infos.family_name.replace(' ', '-')
    name_strings = {
        'familyName': meta_infos.family_name,
        'styleName': meta_infos.style_name,
        'uniqueFontIdentifier': f'{unique_name}-{meta_infos.style_name};{meta_infos.version}',
        'fullName': f'{meta_infos.family_name} {meta_infos.style_name}',
        'version': meta_infos.version,
        'psName': f'{unique_name}-{meta_infos.style_name}',
    }
    if meta_infos.copyright_info is not None:
        name_strings['copyright'] = meta_infos.copyright_info
    if meta_infos.manufacturer is not None:
        name_strings['manufacturer'] = meta_infos.manufacturer
    if meta_infos.designer is not None:
        name_strings['designer'] = meta_infos.designer
    if meta_infos.description is not None:
        name_strings['description'] = meta_infos.description
    if meta_infos.vendor_url is not None:
        name_strings['vendorURL'] = meta_infos.vendor_url
    if meta_infos.designer_url is not None:
        name_strings['designerURL'] = meta_infos.designer_url
    if meta_infos.license_info is not None:
        name_strings['licenseDescription'] = meta_infos.license_info
    if meta_infos.license_url is not None:
        name_strings['licenseInfoURL'] = meta_infos.license_url
    if meta_infos.sample_text is not None:
        name_strings['sampleText'] = meta_infos.sample_text
    return name_strings


def _create_outlines(glyph_data: list[list[int]], px_to_units: int) -> list[list[tuple[int, int]]]:
    """
    将字形数据转换为轮廓数据，左上角原点坐标系
    """
    # 相邻像素分组
    point_group_list = []
    for y, glyph_data_row in enumerate(glyph_data):
        for x, alpha in enumerate(glyph_data_row):
            if alpha > 0:
                new_point_group = {(x, y)}
                for i, point_group in enumerate(reversed(point_group_list)):
                    # 遍历方向为右下，因此只需检查左上
                    if (x - 1, y) in point_group or (x, y - 1) in point_group:
                        point_group_list.remove(point_group)
                        new_point_group = new_point_group.union(point_group)
                point_group_list.append(new_point_group)
    # 对每组生成轮廓
    outlines = []
    for point_group in point_group_list:
        # 按照像素拆分线段，注意绘制顺序
        pending_line_segments = []
        for (x, y) in point_group:
            point_outline = [
                (x * px_to_units, y * px_to_units),
                ((x + 1) * px_to_units, y * px_to_units),
                ((x + 1) * px_to_units, (y + 1) * px_to_units),
                (x * px_to_units, (y + 1) * px_to_units),
            ]
            # 一个像素有左右上下四条边，如果该边没有相邻像素，则该边线段有效
            if x <= 0 or glyph_data[y][x - 1] <= 0:  # 左
                pending_line_segments.append([point_outline[3], point_outline[0]])
            if x >= len(glyph_data[y]) - 1 or glyph_data[y][x + 1] <= 0:  # 右
                pending_line_segments.append([point_outline[1], point_outline[2]])
            if y <= 0 or glyph_data[y - 1][x] <= 0:  # 上
                pending_line_segments.append([point_outline[0], point_outline[1]])
            if y >= len(glyph_data) - 1 or glyph_data[y + 1][x] <= 0:  # 下
                pending_line_segments.append([point_outline[2], point_outline[3]])
        # 连接所有的线段，注意绘制顺序
        solved_line_segments = []
        while len(pending_line_segments) > 0:
            pending_line_segment = pending_line_segments.pop()
            for i, solved_line_segment in enumerate(reversed(solved_line_segments)):
                left_line_segment = None
                right_line_segment = None
                # 一共4种连接情况
                if pending_line_segment[-1] == solved_line_segment[0]:
                    left_line_segment = pending_line_segment
                    right_line_segment = solved_line_segment
                elif pending_line_segment[-1] == solved_line_segment[-1]:
                    solved_line_segment.reverse()
                    left_line_segment = pending_line_segment
                    right_line_segment = solved_line_segment
                elif solved_line_segment[-1] == pending_line_segment[0]:
                    left_line_segment = solved_line_segment
                    right_line_segment = pending_line_segment
                elif solved_line_segment[-1] == pending_line_segment[-1]:
                    pending_line_segment.reverse()
                    left_line_segment = solved_line_segment
                    right_line_segment = pending_line_segment
                # 需要连接的情况
                if left_line_segment is not None and right_line_segment is not None:
                    solved_line_segments.remove(solved_line_segment)
                    # 连接的两个点是重复的
                    right_line_segment.pop(0)
                    # 判断连接的点是不是可省略
                    x, y = left_line_segment[-1]
                    xl, yl = left_line_segment[-2]
                    xr, yr = right_line_segment[0]
                    if (x == xl and x == xr) or (y == yl and y == yr):
                        left_line_segment.pop()
                    # 连接线段
                    pending_line_segment = left_line_segment + right_line_segment
            solved_line_segments.append(pending_line_segment)
        # 将连接好的线段添加到轮廓数组中，有多条线段的情况，是中间有镂空（绘制顺序与外边框相反）
        for solved_line_segment in solved_line_segments:
            # 首尾的两个点是重复的
            solved_line_segment.pop(0)
            # 判断尾点是不是可省略
            x, y = solved_line_segment[-1]
            xl, yl = solved_line_segment[-2]
            xr, yr = solved_line_segment[0]
            if (x == xl and x == xr) or (y == yl and y == yr):
                solved_line_segment.pop()
            # 添加到轮廓
            outlines.append(solved_line_segment)
    return outlines


def _create_glyph(outlines: list[list[tuple[int, int]]], glyph: Glyph, px_to_units: int, is_ttf: bool) -> OTFGlyph | TTFGlyph:
    if is_ttf:
        pen = TTFGlyphPen()
    else:
        pen = OTFGlyphPen(glyph.advance_width * px_to_units, None)
    if len(outlines) > 0:
        for outline_index, outline in enumerate(outlines):
            for point_index, point in enumerate(outline):

                # 转换左上角原点坐标系为左下角原点坐标系
                x, y = point
                x += glyph.offset_x * px_to_units
                y = (glyph.height + glyph.offset_y) * px_to_units - y
                point = x, y

                if point_index == 0:
                    pen.moveTo(point)
                else:
                    pen.lineTo(point)
            if outline_index < len(outlines) - 1:
                pen.endPath()
            else:
                pen.closePath()
    else:
        pen.moveTo((0, 0))
        pen.closePath()
    if is_ttf:
        return pen.glyph()
    else:
        return pen.getCharString()


def create_builder(context: 'font.FontBuilder', is_ttf: bool, flavor: Flavor = None) -> FontBuilder:
    xtf_name = 'TTF' if is_ttf else 'OTF'

    logger.debug("Create '%sBuilder': %s", xtf_name, context.meta_infos.family_name)
    context.check_ready()

    units_per_em = context.size * context.opentype_configs.px_to_units
    builder = FontBuilder(units_per_em, isTTF=is_ttf)

    logger.debug("Setup 'Name Strings'")
    name_strings = _create_name_strings(context.meta_infos)
    builder.setupNameTable(name_strings)

    logger.debug("Setup 'Glyph Order'")
    glyph_order = ['.notdef']
    for _, glyph_name in context.get_character_mapping_sequence():
        if glyph_name not in glyph_order:
            glyph_order.append(glyph_name)
    builder.setupGlyphOrder(glyph_order)
    logger.debug("Setup 'Character Mapping'")
    builder.setupCharacterMap(context.character_mapping)

    logger.debug("Setup 'Glyphs'")
    glyphs = {}
    for glyph_context in context.get_glyphs():
        cache_tag = f'{glyph_context.advance_width}#{glyph_context.offset}#{glyph_context.data}'.replace(' ', '')
        if getattr(glyph_context, _CACHE_NAME_TAG, None) != cache_tag:
            setattr(glyph_context, _CACHE_NAME_OUTLINES, None)
            setattr(glyph_context, _CACHE_NAME_OTF_GLYPH, None)
            setattr(glyph_context, _CACHE_NAME_TTF_GLYPH, None)
            setattr(glyph_context, _CACHE_NAME_TAG, cache_tag)

        outlines = getattr(glyph_context, _CACHE_NAME_OUTLINES, None)
        if outlines is None:
            logger.debug("Create 'Outlines': %s", glyph_context.name)
            outlines = _create_outlines(glyph_context.data, context.opentype_configs.px_to_units)
            setattr(glyph_context, _CACHE_NAME_OUTLINES, outlines)
        else:
            logger.debug("Use cached 'Outlines': %s", glyph_context.name)

        cache_name_xtf_glyph = _CACHE_NAME_TTF_GLYPH if is_ttf else _CACHE_NAME_OTF_GLYPH
        glyph = getattr(glyph_context, cache_name_xtf_glyph, None)
        if glyph is None:
            logger.debug("Create '%sGlyph': %s", xtf_name, glyph_context.name)
            glyph = _create_glyph(outlines, glyph_context, context.opentype_configs.px_to_units, is_ttf)
            setattr(glyph_context, cache_name_xtf_glyph, glyph)
        else:
            logger.debug("Use cached '%sGlyph': %s", xtf_name, glyph_context.name)
        glyphs[glyph_context.name] = glyph
    if is_ttf:
        builder.setupGlyf(glyphs)
    else:
        builder.setupCFF(name_strings['psName'], {'FullName': name_strings['fullName']}, glyphs, {})

    logger.debug("Setup 'Horizontal Metrics'")
    horizontal_metrics = {}
    for glyph_name in glyph_order:
        advance_width = context.get_glyph(glyph_name).advance_width * context.opentype_configs.px_to_units
        if is_ttf:
            lsb = glyphs[glyph_name].xMin
        else:
            lsb = glyphs[glyph_name].calcBounds(None)[0]
        horizontal_metrics[glyph_name] = advance_width, lsb
    builder.setupHorizontalMetrics(horizontal_metrics)

    ascent = context.ascent * context.opentype_configs.px_to_units
    descent = context.descent * context.opentype_configs.px_to_units
    x_height = context.x_height * context.opentype_configs.px_to_units if context.x_height is not None else None
    cap_height = context.cap_height * context.opentype_configs.px_to_units if context.cap_height is not None else None
    logger.debug("Setup 'Horizontal Header'")
    builder.setupHorizontalHeader(
        ascent=ascent,
        descent=descent,
    )
    logger.debug("Setup 'OS2'")
    builder.setupOS2(
        sTypoAscender=ascent,
        sTypoDescender=descent,
        usWinAscent=ascent,
        usWinDescent=-descent,
        sxHeight=x_height,
        sCapHeight=cap_height,
    )

    logger.debug("Setup 'Post'")
    builder.setupPost()

    if flavor is not None:
        logger.debug("Setup 'Flavor': %s", flavor)
        builder.font.flavor = flavor

    logger.debug("Create '%sBuilder' finished", xtf_name)
    return builder


def create_collection_builder(context: 'font.FontCollectionBuilder', is_ttf: bool) -> TTCollection:
    collection_builder = TTCollection()
    for font_context in context.font_builders:
        collection_builder.fonts.append(create_builder(font_context, is_ttf).font)
    return collection_builder

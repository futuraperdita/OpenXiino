"Classes for converting from PIL image to Xiino-format bytes."
import math
from base64 import b64encode
from dataclasses import dataclass
import PIL.Image
import PIL.ImageOps
import bitstring
import cairosvg
import io
import asyncio
from typing import Union

# Security constants
MAX_SVG_SIZE = 1024 * 1024  # 1MB max SVG size
SVG_PROCESSING_TIMEOUT = 5  # 5 second timeout for SVG processing
MAX_PALETTE_OPERATIONS = 500000  # Limit color matching operations

import lib.scanline as scanline
import lib.mode9 as mode9
from lib.xiino_palette_common import PALETTE
from lib.logger import image_logger


@dataclass
class EBDImage:
    """
    An image that has been converted to an EBDIMAGE.
    """

    raw_data: bytes
    width: int
    height: int
    mode: int

    def generate_ebdimage_tag(self, name) -> str:
        "Generate an EBDIMAGE tag for the data of this image."
        base64 = b64encode(self.raw_data).decode("latin-1")
        return (
            f"""<EBDIMAGE MODE="{self.mode}" NAME="{name}"><!--{base64}--></EBDIMAGE>"""
        )

    def generate_img_tag(self, name, alt_text: str | None = None) -> str:
        "Generate an IMG tag for this image."
        return f"""<IMG ALT="{alt_text}" WIDTH="{self.width}" HEIGHT="{self.height}" EBDWIDTH="{self.width}" EBDHEIGHT="{self.height}" EBD="{name}">"""


class EBDConverter:
    """
    Convert from a PIL image to any of the modes known to be supported by Xiino.
    """

    async def __convert_svg(self, svg_content: str, is_file: bool = False) -> PIL.Image.Image:
        """Convert SVG to PNG with security checks"""
        if len(svg_content.encode('utf-8')) > MAX_SVG_SIZE:
            raise ValueError("SVG content exceeds maximum allowed size")
            
        try:
            async with asyncio.timeout(SVG_PROCESSING_TIMEOUT):
                # Run in executor to prevent blocking
                png_data = await asyncio.to_thread(
                    cairosvg.svg2png,
                    url=svg_content if is_file else None,
                    bytestring=svg_content.encode('utf-8') if not is_file else None,
                    parent_width=306,  # Limit initial size
                    parent_height=306
                )
                return PIL.Image.open(io.BytesIO(png_data))
        except asyncio.TimeoutError:
            raise TimeoutError("SVG processing timeout")
        except Exception as e:
            raise ValueError(f"Invalid SVG content: {str(e)}")

    async def __ainit__(
        self, image: Union[PIL.Image.Image, str], override_scale_logic: bool = False
    ) -> None:
        """Async initialization with safety checks and limits"""
        if isinstance(image, str):
            # Process SVG with security checks
            if image.lower().endswith('.svg') or '<svg' in image[:1000].lower():
                image = await self.__convert_svg(image, is_file=image.lower().endswith('.svg'))
            else:
                # Open regular image file with size validation
                image = PIL.Image.open(image)
                if image.width * image.height > 1000000:  # e.g. 1000x1000
                    raise ValueError("Image dimensions too large")

    def __init__(
        self, image: Union[PIL.Image.Image, str], override_scale_logic: bool = False
    ) -> None:
        """Initialize with safety checks and limits"""
        self._image = image
        self._override_scale_logic = override_scale_logic
        self._init_complete = asyncio.Event()
        self.image = None
        
        # Start initialization
        asyncio.create_task(self._initialize())
        
    async def _initialize(self) -> None:
        """Initialize the converter asynchronously"""
        try:
            if isinstance(self._image, str):
                # Process SVG with security checks
                if self._image.lower().endswith('.svg') or '<svg' in self._image[:1000].lower():
                    image = await self.__convert_svg(
                        self._image, 
                        is_file=self._image.lower().endswith('.svg')
                    )
                else:
                    # Open regular image file with size validation
                    image = PIL.Image.open(self._image)
                    if image.width * image.height > 1000000:
                        raise ValueError("Image dimensions too large")
            else:
                image = self._image

            # Apply scaling logic
            if not self._override_scale_logic:
                if image.width > 306:
                    new_width = 153
                    new_height = math.ceil((image.height / image.width) * 153)
                else:
                    new_width = math.ceil(image.width / 2)
                    new_height = math.ceil(image.height / 2)

                image = image.resize((new_width, new_height))

            # Handle transparency
            try:
                if image.mode == "RGBA":
                    background = PIL.Image.new("RGBA", image.size, (255, 255, 255))
                    self.image = PIL.Image.alpha_composite(background, image).convert("RGB")
                else:
                    self.image = image.convert("RGB")  # Just in case :)
            except ValueError as exception_data:
                image_logger.error(f"Image composite failed for size {image.size}")
                raise exception_data
                
            self._init_complete.set()
        except Exception as e:
            image_logger.error(f"Initialization failed: {str(e)}")
            raise
            
    async def _ensure_initialized(self) -> None:
        """Ensure the converter is initialized before operations"""
        await self._init_complete.wait()

    async def convert_bw(self, compressed: bool = False) -> EBDImage:
        """
        Convert the image to black and white (1-bit.)
        For greyscale, use `convert_gs`.
        """
        await self._ensure_initialized()
        if compressed:
            return EBDImage(
                self.__convert_mode1(),
                width=self.image.width,
                height=self.image.height,
                mode=1,
            )
        return EBDImage(
            self.__convert_mode0(),
            width=self.image.width,
            height=self.image.height,
            mode=0,
        )

    async def convert_gs(self, depth=4, compressed: bool = False) -> EBDImage:
        """
        Convert the image to greyscale.
        Defaults to 16-grey (4-bit) mode. For 4-grey (2-bit) mode,
        set `depth=2`.
        """
        await self._ensure_initialized()
        if depth == 2:
            if compressed:
                return EBDImage(
                    self.__convert_mode3(),
                    width=self.image.width,
                    height=self.image.height,
                    mode=3,
                )
            return EBDImage(
                self.__convert_mode2(),
                width=self.image.width,
                height=self.image.height,
                mode=2,
            )
        elif depth == 4:
            if compressed:
                return EBDImage(
                    self.__convert_mode4(),
                    width=self.image.width,
                    height=self.image.height,
                    mode=4,
                )
            return EBDImage(
                self.__convert_mode5(),
                width=self.image.width,
                height=self.image.height,
                mode=5,
            )
        else:
            raise ValueError("Unsupported bit depth for greyscale.")

    async def convert_colour(self, compressed: bool = False) -> EBDImage:
        "Convert the image to 8-bit (231 colour)."
        await self._ensure_initialized()
        if compressed:
            return EBDImage(
                mode9.compress_mode9(self.image),
                width=self.image.width,
                height=self.image.height,
                mode=9,
            )
        return EBDImage(
            self.__convert_mode8(),
            width=self.image.width,
            height=self.image.height,
            mode=8,
        )

    def __convert_mode0(self) -> bytes:
        """
        Internal function for converting to mode0 (one-bit, no compression.)
        """
        buf = []
        im_bw = self.image.convert("1")
        for y in range(0, self.image.height):
            row_data = [im_bw.getpixel((x, y)) for x in range(0, self.image.width)]
            for chunk in self.__divide_chunks(row_data, 8):
                binary = bitstring.BitArray(bin="0b00000000")
                index = 0
                for pixel in chunk:
                    if pixel:
                        binary.set(False, index)
                    else:
                        binary.set(True, index)
                    index += 1
                buf.append(binary.uint)
        return bytes(buf)

    def __convert_mode1(self) -> bytes:
        """
        Internal function for converting to mode1 (one-bit, scanline compression)
        """
        # TODO writing a scanline converter is hurting my brain. later.
        return self.__convert_mode0()

    def __convert_mode2(self) -> bytes:
        """
        Internal function to convert to uncompressed two-bit grey.
        """
        buf = []
        im_gs = PIL.ImageOps.invert(self.image.convert("L"))
        raw_data = list(im_gs.getdata())
        for y in range(0, self.image.height):
            raw_data = [im_gs.getpixel((x, y)) for x in range(0, self.image.width)]
            for chunk in self.__divide_chunks(raw_data, 4):
                if len(chunk) == 1:
                    byte = math.floor(chunk[0] / 64) << 6
                elif len(chunk) == 2:
                    byte = (
                        math.floor(chunk[0] / 64) << 6 | math.floor(chunk[1] / 64) << 4
                    )
                elif len(chunk) == 3:
                    byte = (
                        math.floor(chunk[0] / 64) << 6
                        | math.floor(chunk[1] / 64) << 4
                        | math.floor(chunk[2] / 64) << 2
                    )
                elif len(chunk) == 4:
                    byte = (
                        math.floor(chunk[0] / 64) << 6
                        | math.floor(chunk[1] / 64) << 4
                        | math.floor(chunk[2] / 64) << 2
                        | math.floor(chunk[3] / 64)
                    )
                buf.append(byte)

        return bytes(buf)

    def __convert_mode3(self) -> bytes:
        """
        Internal function to convert to Scanline compressed two-bit grey.
        """
        width_bytes = math.ceil(self.image.width / 2)
        return scanline.compress_data_with_scanline(self.__convert_mode2(), width_bytes)

    def __convert_mode4(self) -> bytes:
        """
        Internal function to convert to uncompressed four-bit grey.
        """
        buf = []
        im_gs = PIL.ImageOps.invert(self.image.convert("L"))
        for y in range(0, self.image.height):
            raw_data = [im_gs.getpixel((x, y)) for x in range(0, self.image.width)]
            for chunk in self.__divide_chunks(raw_data, 2):
                # Scale values to 0-15 range for 4-bit grayscale
                val1 = min(15, round(chunk[0] / 16))
                val2 = 0 if len(chunk) < 2 else min(15, round(chunk[1] / 16))
                byte = (val1 << 4) | val2
                buf.append(byte)

        return bytes(buf)

    def __convert_mode5(self) -> bytes:
        """
        Internal function to convert to Scanline compressed four-bit grey.
        """
        width_bytes = math.ceil(self.image.width / 4)
        return scanline.compress_data_with_scanline(self.__convert_mode4(), width_bytes)

    def __convert_mode8(self) -> bytes:
        """Convert to 8-bit color with operation limits and optimizations"""
        buf = bytearray()
        pixel_count = 0
        palette_cache = {}  # Cache color matches
        
        for px in self.image.getdata():
            # Check operation limits
            pixel_count += 1
            if pixel_count * len(PALETTE) > MAX_PALETTE_OPERATIONS:
                raise ValueError("Image processing exceeded operation limit")
                
            # Use cached color match if available
            px_key = hash(px)
            if px_key in palette_cache:
                buf.append(palette_cache[px_key])
                continue
                
            # Find closest color in palette using Euclidean distance
            min_distance = float('inf')
            best_index = 0xE6  # Default, but should never be used
            r, g, b = px
            
            for i, (pr, pg, pb) in enumerate(PALETTE):
                # Calculate color distance
                distance = (r - pr) ** 2 + (g - pg) ** 2 + (b - pb) ** 2
                if distance < min_distance:
                    min_distance = distance
                    best_index = i
                    
            # Cache the result
            palette_cache[px_key] = best_index
            buf.append(best_index)
            
            # Limit cache size
            if len(palette_cache) > 1000:
                palette_cache.clear()
                
        return buf

    def __divide_chunks(self, l: list, n: int):
        "Helper function for splitting things into chunks"
        for i in range(0, len(l), n):
            yield l[i : i + n]

"""Classes for converting from PIL image to Xiino-format bytes."""
import math
from base64 import b64encode
from dataclasses import dataclass
import PIL.Image
import PIL.ImageOps
import bitstring
import cairosvg
import io
import asyncio
from typing import Union, Optional, List, Tuple, Dict, Any
from concurrent.futures import ThreadPoolExecutor

# Security constants
MAX_SVG_SIZE = 1024 * 1024  # 1MB max SVG size
SVG_PROCESSING_TIMEOUT = 5  # 5 second timeout for SVG processing
MAX_PALETTE_OPERATIONS = 500000  # Limit color matching operations

import lib.scanline as scanline
import lib.mode9 as mode9
from lib.xiino_palette_common import PALETTE
from lib.logger import image_logger

# Thread pool for CPU-intensive operations
_thread_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="ebd_converter")

@dataclass
class EBDImage:
    """An image that has been converted to an EBDIMAGE format."""
    raw_data: bytes
    width: int
    height: int
    mode: int

    def generate_ebdimage_tag(self, name: str) -> str:
        """Generate an EBDIMAGE tag for the data of this image."""
        base64 = b64encode(self.raw_data).decode("latin-1")
        return (
            f"""<EBDIMAGE MODE="{self.mode}" NAME="{name}"><!--{base64}--></EBDIMAGE>"""
        )

    def generate_img_tag(self, name: str, alt_text: Optional[str] = None) -> str:
        """Generate an IMG tag for this image."""
        return f"""<IMG ALT="{alt_text or ''}" WIDTH="{self.width}" HEIGHT="{self.height}" EBDWIDTH="{self.width}" EBDHEIGHT="{self.height}" EBD="{name}">"""

class EBDConverter:
    """Convert from a PIL image to any of the modes known to be supported by Xiino."""

    def __init__(
        self,
        image: Union[PIL.Image.Image, str],
        override_scale_logic: bool = False
    ) -> None:
        """Initialize with safety checks and limits."""
        self._image = image
        self._override_scale_logic = override_scale_logic
        self._init_complete = asyncio.Event()
        self.image: Optional[PIL.Image.Image] = None
        self._cleanup_required = False
        
        # Start initialization
        asyncio.create_task(self._initialize())

    async def cleanup(self) -> None:
        """Clean up resources."""
        if self._cleanup_required and self.image:
            await asyncio.to_thread(self.image.close)
            self.image = None
            self._cleanup_required = False

    def __extract_svg_dimensions(self, svg_content: str) -> Tuple[int, int]:
        """Extract width and height from SVG content."""
        import re
        
        # Try to extract from width/height attributes with units
        width_match = re.search(r'width="(\d+(?:\.\d+)?)\s*(?:px|pt|mm|cm|in|%)?', svg_content)
        height_match = re.search(r'height="(\d+(?:\.\d+)?)\s*(?:px|pt|mm|cm|in|%)?', svg_content)
        
        if width_match and height_match:
            width = float(width_match.group(1))
            height = float(height_match.group(1))
            # If dimensions are percentages, try to get actual size from viewBox
            if '%' in width_match.group(0) or '%' in height_match.group(0):
                viewbox_match = re.search(r'viewBox="[^"]*?\s+[^"]*?\s+(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)"', svg_content)
                if viewbox_match:
                    return int(float(viewbox_match.group(1))), int(float(viewbox_match.group(2)))
            return int(width), int(height)
            
        # Try to extract from viewBox
        viewbox_match = re.search(r'viewBox="[^"]*?\s+[^"]*?\s+(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)"', svg_content)
        if viewbox_match:
            return int(float(viewbox_match.group(1))), int(float(viewbox_match.group(2)))
            
        # Default to device width if no dimensions found
        return 306, 306

    async def _convert_svg(self, svg_content: str, is_file: bool = False) -> PIL.Image.Image:
        """Convert SVG to PNG with security checks and proper scaling."""
        if len(svg_content.encode('utf-8')) > MAX_SVG_SIZE:
            raise ValueError("SVG content exceeds maximum allowed size")
            
        try:
            # Extract original dimensions
            orig_width, orig_height = self.__extract_svg_dimensions(svg_content)
            
            # Calculate target dimensions maintaining aspect ratio
            if orig_width < 100 and orig_height < 100:
                target_width = orig_width
                target_height = orig_height
            else:
                target_width = 153 if orig_width > 306 else math.ceil(orig_width / 2)
                scale_factor = target_width / orig_width
                target_height = math.ceil(orig_height * scale_factor)
            
            async with asyncio.timeout(SVG_PROCESSING_TIMEOUT):
                # Run in executor to prevent blocking
                png_data = await asyncio.to_thread(
                    cairosvg.svg2png,
                    url=svg_content if is_file else None,
                    bytestring=svg_content.encode('utf-8') if not is_file else None,
                    output_width=target_width,
                    output_height=target_height,
                    scale=1.0
                )
                return PIL.Image.open(io.BytesIO(png_data))
        except asyncio.TimeoutError:
            raise TimeoutError("SVG processing timeout")
        except Exception as e:
            raise ValueError(f"Invalid SVG content: {str(e)}")

    async def _initialize(self) -> None:
        """Initialize the converter asynchronously."""
        try:
            if isinstance(self._image, str):
                # Process SVG with security checks
                if self._image.lower().endswith('.svg') or '<svg' in self._image[:1000].lower():
                    image = await self._convert_svg(
                        self._image, 
                        is_file=self._image.lower().endswith('.svg')
                    )
                else:
                    # Open regular image file with size validation
                    image = await asyncio.to_thread(PIL.Image.open, self._image)
                    if image.width * image.height > 1000000:
                        raise ValueError("Image dimensions too large")
            else:
                image = self._image

            # Apply scaling logic only for non-SVG images
            if not self._override_scale_logic and not (
                isinstance(self._image, str) and 
                (self._image.lower().endswith('.svg') or '<svg' in self._image[:1000].lower())
            ):
                if image.width > 306:
                    new_width = 153
                    new_height = math.ceil((image.height / image.width) * 153)
                else:
                    new_width = math.ceil(image.width / 2)
                    new_height = math.ceil(image.height / 2)

                image = await asyncio.to_thread(
                    image.resize,
                    (new_width, new_height),
                    PIL.Image.Resampling.LANCZOS
                )

            # Handle transparency
            try:
                # Convert palette images with transparency to RGBA first
                if image.mode == "P" and image.info.get("transparency") is not None:
                    image = await asyncio.to_thread(image.convert, "RGBA")
                
                if image.mode == "RGBA":
                    background = PIL.Image.new("RGBA", image.size, (255, 255, 255))
                    self.image = await asyncio.to_thread(
                        lambda: PIL.Image.alpha_composite(background, image).convert("RGB")
                    )
                else:
                    self.image = await asyncio.to_thread(image.convert, "RGB")
            except ValueError as e:
                image_logger.error(f"Image composite failed for size {image.size}")
                raise e
                
            self._cleanup_required = True
            self._init_complete.set()
        except Exception as e:
            image_logger.error(f"Initialization failed: {str(e)}")
            raise

    async def _ensure_initialized(self) -> None:
        """Ensure the converter is initialized before operations."""
        await self._init_complete.wait()

    async def convert_bw(self, compressed: bool = False) -> EBDImage:
        """Convert the image to black and white (1-bit)."""
        await self._ensure_initialized()
        if compressed:
            data = await asyncio.to_thread(self._convert_mode1)
            return EBDImage(data, width=self.image.width, height=self.image.height, mode=1)
        data = await asyncio.to_thread(self._convert_mode0)
        return EBDImage(data, width=self.image.width, height=self.image.height, mode=0)

    async def convert_gs(self, depth: int = 4, compressed: bool = False) -> EBDImage:
        """Convert the image to greyscale."""
        await self._ensure_initialized()
        if depth == 2:
            if compressed:
                data = await asyncio.to_thread(self._convert_mode3)
                return EBDImage(data, width=self.image.width, height=self.image.height, mode=3)
            data = await asyncio.to_thread(self._convert_mode2)
            return EBDImage(data, width=self.image.width, height=self.image.height, mode=2)
        elif depth == 4:
            if compressed:
                data = await asyncio.to_thread(self._convert_mode4)
                return EBDImage(data, width=self.image.width, height=self.image.height, mode=4)
            data = await asyncio.to_thread(self._convert_mode5)
            return EBDImage(data, width=self.image.width, height=self.image.height, mode=5)
        else:
            raise ValueError("Unsupported bit depth for greyscale.")

    async def convert_colour(self, compressed: bool = False) -> EBDImage:
        """Convert the image to 8-bit (231 colour)."""
        await self._ensure_initialized()
        if compressed:
            data = await asyncio.to_thread(mode9.compress_mode9, self.image)
            return EBDImage(data, width=self.image.width, height=self.image.height, mode=9)
        data = await asyncio.to_thread(self._convert_mode8)
        return EBDImage(data, width=self.image.width, height=self.image.height, mode=8)

    def _convert_mode0(self) -> bytes:
        """Convert to mode0 (one-bit, no compression)."""
        buf = []
        im_bw = self.image.convert("1")
        for y in range(0, self.image.height):
            row_data = [im_bw.getpixel((x, y)) for x in range(0, self.image.width)]
            for chunk in self._divide_chunks(row_data, 8):
                binary = bitstring.BitArray(bin="0b00000000")
                for index, pixel in enumerate(chunk):
                    binary.set(not pixel, index)
                buf.append(binary.uint)
        return bytes(buf)

    def _convert_mode1(self) -> bytes:
        """Convert to mode1 (one-bit, scanline compression)."""
        width_bytes = math.ceil(self.image.width / 2)
        return scanline.compress_data_with_scanline(self._convert_mode0(), width_bytes)

    def _convert_mode2(self) -> bytes:
        """Convert to uncompressed two-bit grey."""
        buf = []
        im_gs = PIL.ImageOps.invert(self.image.convert("L"))
        for y in range(0, self.image.height):
            raw_data = [im_gs.getpixel((x, y)) for x in range(0, self.image.width)]
            for chunk in self._divide_chunks(raw_data, 4):
                byte = 0
                for i, val in enumerate(reversed(chunk)):
                    byte |= (math.floor(val / 64) << (i * 2))
                buf.append(byte)
        return bytes(buf)

    def _convert_mode3(self) -> bytes:
        """Convert to Scanline compressed two-bit grey."""
        width_bytes = math.ceil(self.image.width / 2)
        return scanline.compress_data_with_scanline(self._convert_mode2(), width_bytes)

    def _convert_mode4(self) -> bytes:
        """Convert to uncompressed four-bit grey."""
        buf = []
        im_gs = PIL.ImageOps.invert(self.image.convert("L"))
        for y in range(0, self.image.height):
            raw_data = [im_gs.getpixel((x, y)) for x in range(0, self.image.width)]
            for chunk in self._divide_chunks(raw_data, 2):
                val1 = min(15, round(chunk[0] / 16))
                val2 = 0 if len(chunk) < 2 else min(15, round(chunk[1] / 16))
                buf.append((val1 << 4) | val2)
        return bytes(buf)

    def _convert_mode5(self) -> bytes:
        """Convert to Scanline compressed four-bit grey."""
        width_bytes = math.ceil(self.image.width / 4)
        return scanline.compress_data_with_scanline(self._convert_mode4(), width_bytes)

    def _convert_mode8(self) -> bytes:
        """Convert to 8-bit color with operation limits and optimizations."""
        buf = bytearray()
        pixel_count = 0
        palette_cache: Dict[int, int] = {}
        
        for px in self.image.getdata():
            pixel_count += 1
            if pixel_count * len(PALETTE) > MAX_PALETTE_OPERATIONS:
                raise ValueError("Image processing exceeded operation limit")
                
            px_key = hash(px)
            if px_key in palette_cache:
                buf.append(palette_cache[px_key])
                continue
                
            r, g, b = px
            min_distance = float('inf')
            best_index = 0xE6
            
            for i, (pr, pg, pb) in enumerate(PALETTE):
                distance = (r - pr) ** 2 + (g - pg) ** 2 + (b - pb) ** 2
                if distance < min_distance:
                    min_distance = distance
                    best_index = i
                    
            palette_cache[px_key] = best_index
            buf.append(best_index)
            
            if len(palette_cache) > 1000:
                palette_cache.clear()
                
        return buf

    @staticmethod
    def _divide_chunks(l: List[Any], n: int) -> List[Any]:
        """Helper function for splitting things into chunks."""
        return [l[i:i + n] for i in range(0, len(l), n)]

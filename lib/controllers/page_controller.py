from pybars import Compiler
import os
import asyncio
from typing import Dict, Optional
from dotenv import load_dotenv

# Load environment variables
load_dotenv()
MAX_PAGE_SIZE = int(os.getenv('MAX_PAGE_SIZE', 100))  # Default to 100KB if not set

class PageController:
    """Controller for handling page routes and rendering templates"""
    
    def __init__(self):
        self.compiler = Compiler()
        self.templates: Dict[str, callable] = {}
        self._initialized = False
        
    @classmethod
    async def create(cls) -> 'PageController':
        """Async factory method for creating PageController instance"""
        controller = cls()
        await controller._initialize()
        return controller
        
    async def _initialize(self) -> None:
        """Initialize the controller asynchronously"""
        if not self._initialized:
            await self._load_templates()
            self._initialized = True

    def _gt(self, this, *args):
        """Helper function for greater than comparison"""
        if len(args) != 2:
            return False
        try:
            return float(args[0]) > float(args[1])
        except (ValueError, TypeError):
            return False
    
    @staticmethod
    def _load_template_file(path: str) -> str:
        """Helper for loading template file content"""
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()
    
    async def _load_templates(self) -> None:
        """Load and compile all handlebars templates asynchronously"""
        template_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'templates')
        template_tasks = []
        
        for template_file in os.listdir(template_dir):
            if template_file.endswith('.hbs'):
                template_path = os.path.join(template_dir, template_file)
                template_name = os.path.splitext(template_file)[0]
                # Create task for loading template
                task = asyncio.create_task(self._load_and_compile_template(template_name, template_path))
                template_tasks.append(task)
                
        # Wait for all templates to load
        await asyncio.gather(*template_tasks)
    
    async def _load_and_compile_template(self, name: str, path: str) -> None:
        """Load and compile a single template"""
        content = await asyncio.to_thread(self._load_template_file, path)
        self.templates[name] = self.compiler.compile(content)
    
    def _check_content_size(self, content: str) -> bool:
        """Check if content size exceeds the maximum allowed size
        
        Args:
            content: The rendered page content to check
            
        Returns:
            bool: True if content is within size limit, False otherwise
        """
        content_size_kb = len(content.encode('utf-8')) / 1024
        return content_size_kb <= MAX_PAGE_SIZE
    
    def _render_page_too_large(self) -> str:
        """Render the page too large error page"""
        context = {
            'title': 'Page Too Large',
            'max_size': MAX_PAGE_SIZE
        }
        return self.templates['page_too_large'](context)

    async def handle_page(self, page: str, request_info: Optional[dict] = None) -> str:
        """Handle page requests asynchronously"""
        # Ensure initialization
        if not self._initialized:
            await self._initialize()
            
        # First render the requested page
        content = None

        if page == 'home':
            content = await self._render_about()
        elif page == 'more':
            content = await self._render_more_info()
        elif page == 'device':
            content = await self._render_device_info(request_info)
        elif page == 'github':
            content = await self._render_github()
        elif page == 'error_toolarge':
            content = await self._render_page_too_large()
        elif page == 'image' and isinstance(request_info, dict):
            content = await self._render_image(
                request_info.get('image_url', ''),
                request_info.get('image_html', '')
            )
        else:
            content = await self._render_not_found()
            
        return content
    
    async def _render_about(self) -> str:
        """Render the about page"""
        context = {
            'title': 'About OpenXiino',
            'logo': {
                'alt': 'OpenXiino logo',
                'width': 104,
                'height': 63,
                'ebd_ref': 1
            }
        }
        return await asyncio.to_thread(self.templates['about'], context)
    
    async def _render_more_info(self) -> str:
        """Render the more info page"""
        context = {
            'title': 'More About OpenXiino'
        }
        return await asyncio.to_thread(self.templates['more_info'], context)
    
    async def _render_device_info(self, request_info: Optional[dict]) -> str:
        """Render the device info page"""
        if not request_info:
            request_info = {}
            
        context = {
            'title': 'Device Info',
            'color_depth': request_info.get('color_depth'),
            'grayscale_depth': request_info.get('grayscale_depth'),
            'screen_width': request_info.get('screen_width'),
            'encoding': request_info.get('encoding'),
            'headers': request_info.get('headers', '')
        }
        helpers = {'gt': self._gt}
        return await asyncio.to_thread(self.templates['device_info'], context, helpers=helpers)
    
    async def _render_github(self) -> str:
        """Render the GitHub page"""
        context = {
            'title': 'GitHub'
        }
        return await asyncio.to_thread(self.templates['github'], context)
    
    async def _render_not_found(self) -> str:
        """Render a 404 page"""
        context = {
            'title': 'Page Not Found'
        }
        return await asyncio.to_thread(self.templates['not_found'], context)
        
    async def _render_image(self, image_url: str, image_html: str) -> str:
        """Render an image view page
        
        Args:
            image_url: The original URL of the image
            image_html: The HTML containing the IMG and EBDIMAGE tags
            
        Returns:
            str: The rendered image page
        """
        context = {
            'image_url': image_url,
            'image_html': image_html
        }
        return await asyncio.to_thread(self.templates['image'], context)

    async def cleanup(self) -> None:
        """Cleanup resources"""
        self.templates.clear()
        self._initialized = False

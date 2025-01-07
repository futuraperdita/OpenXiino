from pybars import Compiler
import os

class PageController:
    """Controller for handling page routes and rendering templates"""
    
    def __init__(self):
        self.compiler = Compiler()
        self.templates = {}
        self._load_templates()

    def _gt(self, this, *args):
        """Helper function for greater than comparison"""
        if len(args) != 2:
            return False
        try:
            return float(args[0]) > float(args[1])
        except (ValueError, TypeError):
            return False
    
    def _load_templates(self):
        """Load and compile all handlebars templates"""
        template_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'templates')
        for template_file in os.listdir(template_dir):
            if template_file.endswith('.hbs'):
                template_path = os.path.join(template_dir, template_file)
                with open(template_path, 'r', encoding='utf-8') as f:
                    template_name = os.path.splitext(template_file)[0]
                    self.templates[template_name] = self.compiler.compile(f.read())
    
    def handle_page(self, page: str, request_info=None) -> str:
        """Handle page requests"""
        if page == 'home':
            return self._render_about()
        elif page == 'more':
            return self._render_more_info()
        elif page == 'device':
            return self._render_device_info(request_info)
        elif page == 'github':
            return self._render_github()
        else:
            return self._render_not_found()
    
    def _render_about(self) -> str:
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
        return self.templates['about'](context)
    
    def _render_more_info(self) -> str:
        """Render the more info page"""
        context = {
            'title': 'More About OpenXiino'
        }
        return self.templates['more_info'](context)
    
    def _render_device_info(self, request_info) -> str:
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
        return self.templates['device_info'](context, helpers=helpers)
    
    def _render_github(self) -> str:
        """Render the GitHub page"""
        context = {
            'title': 'GitHub'
        }
        return self.templates['github'](context)
    
    def _render_not_found(self) -> str:
        """Render a 404 page"""
        context = {
            'title': 'Page Not Found'
        }
        return self.templates['not_found'](context)

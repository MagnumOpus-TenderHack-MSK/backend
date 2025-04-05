from fastapi import Request


# Helper function to check if a path should bypass auth
def should_bypass_auth(request: Request) -> bool:
    """
    Check if the request path should bypass authentication.
    Public routes that don't need authentication.
    """
    public_paths = [
        '/api/files/{file_id}/download',
        '/api/files/{file_id}/preview',
        '/static',
        '/health',
        '/',
        '/docs',
        '/redoc',
        '/openapi.json',
        '/api/auth/login',
        '/api/auth/register'
    ]

    path = request.url.path

    # Check if path matches any public path pattern
    for public_path in public_paths:
        # Check for static files path
        if public_path == '/static' and path.startswith('/static'):
            return True

        # Handle path parameters
        if '{' in public_path:
            # Convert path parameter format to regex pattern
            pattern = public_path.replace('{', '').replace('}', '[^/]+')
            if path.startswith(pattern.split('[')[0]) and path.endswith(pattern.split(']')[-1]):
                return True

        # Direct path match
        elif path == public_path:
            return True

    return False
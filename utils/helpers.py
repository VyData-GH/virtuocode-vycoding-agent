import hashlib
import hmac
import re
from typing import Any, Dict, Optional
from datetime import datetime
import os


def validate_webhook_signature(payload: Dict[str, Any], signature: str, secret: str) -> bool:
    try:
        import json
        payload_bytes = json.dumps(payload, sort_keys=True).encode('utf-8')
        
        expected_signature = hmac.new(
            secret.encode('utf-8'),
            payload_bytes,
            hashlib.sha256
        ).hexdigest()
        
        return hmac.compare_digest(signature, expected_signature)
        
    except Exception:
        return False


def sanitize_branch_name(name: str) -> str:
    clean_name = name.lower()
    
    clean_name = re.sub(r'[^\w\s-]', '', clean_name)
    clean_name = re.sub(r'\s+', '-', clean_name)
    clean_name = re.sub(r'-+', '-', clean_name)
    clean_name = clean_name.strip('-')

    if len(clean_name) > 50:
        clean_name = clean_name[:50].rstrip('-')
    
    if not clean_name:
        clean_name = "unnamed-branch"
    
    return clean_name


def generate_unique_branch_name(base_name: str, prefix: str = "feature") -> str:

    clean_base = sanitize_branch_name(base_name)
    timestamp = datetime.now().strftime("%m%d-%H%M")
    
    return f"{prefix}/{clean_base}-{timestamp}"


def extract_error_details(error: Exception) -> Dict[str, Any]:

    import traceback
    
    return {
        "type": type(error).__name__,
        "message": str(error),
        "traceback": traceback.format_exc() if hasattr(error, '__traceback__') else None
    }


def format_duration(seconds: float) -> str:

    if seconds < 1:
        return f"{seconds:.2f}s"
    elif seconds < 60:
        return f"{int(seconds)}s"
    elif seconds < 3600:
        minutes = int(seconds // 60)
        remaining_seconds = int(seconds % 60)
        return f"{minutes}m {remaining_seconds}s"
    else:
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        return f"{hours}h {minutes}m"


def truncate_text(text: str, max_length: int = 100, suffix: str = "...") -> str:

    if len(text) <= max_length:
        return text
    
    return text[:max_length - len(suffix)] + suffix


def safe_get_nested(data: Dict[str, Any], keys: str, default: Any = None) -> Any:

    try:
        current = data
        for key in keys.split('.'):
            current = current[key]
        return current
    except (KeyError, TypeError, AttributeError):
        return default


def merge_dicts(*dicts: Dict[str, Any]) -> Dict[str, Any]:
    """
    Fusionne plusieurs dictionnaires.
    
    Args:
        *dicts: Dictionnaires à fusionner
        
    Returns:
        Dictionnaire fusionné
    """
    result = {}
    for d in dicts:
        if d:
            result.update(d)
    return result


def is_valid_git_branch_name(name: str) -> bool:
    """
    Vérifie si un nom est valide pour une branche Git.
    
    Args:
        name: Nom à vérifier
        
    Returns:
        True si le nom est valide
    """
    if not name:
        return False
    
    
    invalid_patterns = [
        r'\.\.', r'\s', r'~', r'\^', r':', r'\?', r'\*', r'\[',
        r'\\', r'//', r'@\{', r'^\.', r'\.$', r'\.lock$'
    ]
    
    for pattern in invalid_patterns:
        if re.search(pattern, name):
            return False
    
    return True


def extract_repo_info_from_url(url: str) -> Optional[Dict[str, str]]:

    try:
        # Nettoyer l'URL
        clean_url = url.strip()
        if clean_url.endswith('.git'):
            clean_url = clean_url[:-4]
        
        patterns = [
            r'github\.com[:/]([^/]+)/([^/]+)',
            r'gitlab\.com[:/]([^/]+)/([^/]+)',
            r'bitbucket\.org[:/]([^/]+)/([^/]+)'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, clean_url)
            if match:
                return {
                    "owner": match.group(1),
                    "repo": match.group(2),
                    "full_name": f"{match.group(1)}/{match.group(2)}"
                }
        
        return None
        
    except Exception:
        return None

# Etapes de l'optimisation
def sanitize_filename(filename: str) -> str:
    invalid_chars = r'[<>:"/\\|?*\x00-\x1f]'
    
    clean_name = re.sub(invalid_chars, '_', filename)

    clean_name = clean_name.strip('. ')

    if len(clean_name) > 200:
        name, ext = os.path.splitext(clean_name)
        clean_name = name[:200-len(ext)] + ext
    
    return clean_name or "unnamed_file"


def create_status_emoji(success: bool, partial: Optional[bool] = None) -> str:

    if success:
        return "✅"
    elif partial:
        return "⚠️"
    else:
        return "❌"


def parse_test_output(output: str) -> Dict[str, Any]:

    result = {
        "total_tests": 0,
        "passed": 0,
        "failed": 0,
        "errors": [],
        "framework": "unknown"
    }
 
    patterns = {
        "pytest": {
            "total": r'(\d+) passed',
            "failed": r'(\d+) failed',
            "framework": "pytest"
        },
        "jest": {
            "total": r'Tests:\s+(\d+) passed',
            "failed": r'(\d+) failed',
            "framework": "jest"
        },
        "unittest": {
            "total": r'Ran (\d+) tests',
            "failed": r'FAILED \(.*failures=(\d+)',
            "framework": "unittest"
        }
    }
    
    for framework, pattern_dict in patterns.items():
        if framework.lower() in output.lower():
            result["framework"] = framework
            
            for key, pattern in pattern_dict.items():
                if key in ["total", "failed"]:
                    match = re.search(pattern, output)
                    if match:
                        result[key if key != "total" else "total_tests"] = int(match.group(1))
            
            break
    
    result["passed"] = max(0, result["total_tests"] - result["failed"])
    
    error_patterns = [r'FAIL.*', r'ERROR.*', r'AssertionError.*', r'TypeError.*']
    
    for pattern in error_patterns:
        matches = re.findall(pattern, output, re.MULTILINE)
        result["errors"].extend(matches[:5])
    
    return result
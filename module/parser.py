# -*- coding: utf-8 -*-
"""
Created on Sun Feb 25 20:42:17 2024
@author: seesthenight & Circle D5
"""
import re
import json

# ==================== Regex Patterns ====================
RE_PARAM_CODE = r'\s*([\w ]+):\s*("(?:\\.|[^\\"])+"|[^,]*)(?:,|$)'
RE_PARAM = re.compile(RE_PARAM_CODE)
RE_IMAGESIZE = re.compile(r"^(\d+)x(\d+)$")
RE_HYPERNET_HASH = re.compile(r"\(([0-9a-f]+)\)$")

# ==================== Utility Functions ====================
def unquote(text: str) -> str:
    """Unquote a JSON-style quoted string, fallback to original if fails."""
    if not text or text[0] != '"' or text[-1] != '"':
        return text
    try:
        return json.loads(text)
    except Exception:
        return text

# ==================== SwarmUI Parser ====================
def parse_swarmui_parameters(param_str: str) -> dict:
    """
    Parse SwarmUI parameters from JSON string.
    Returns a dictionary with standardized field names matching WebUI format.
    """
    try:
        data = json.loads(param_str)
    except json.JSONDecodeError as e:
        print(f"Failed to parse SwarmUI JSON: {e}")
        return {}
    
    sui_params = data.get('sui_image_params', {})
    sui_extra = data.get('sui_extra_data', {})
    sui_models = data.get('sui_models', [])
    
    res = {}
    
    # Map SwarmUI fields to standard WebUI field names
    res['Prompt'] = sui_params.get('prompt', '')
    res['Negative prompt'] = sui_params.get('negativeprompt', '')
    res['Steps'] = str(sui_params.get('steps', ''))
    res['CFG scale'] = str(sui_params.get('cfgscale', ''))
    res['Seed'] = str(sui_params.get('seed', ''))
    res['Sampler'] = sui_params.get('sampler', '')
    res['Clip skip'] = str(abs(sui_params.get('clipstopatlayer', -2)))
    
    # Image dimensions
    if 'width' in sui_params and 'height' in sui_params:
        res['Size-1'] = str(sui_params['width'])
        res['Size-2'] = str(sui_params['height'])
    
    # Model information
    if sui_models:
        model_info = sui_models[0]
        model_name = model_info.get('name', '').replace('.safetensors', '')
        res['Model'] = model_name
        
        # Extract hash if available
        model_hash = model_info.get('hash', '')
        if model_hash.startswith('0x'):
            # Take first 10 characters after '0x' for consistency with WebUI
            res['Model hash'] = model_hash[2:12]
        elif model_hash:
            res['Model hash'] = model_hash[:10]
    else:
        res['Model'] = sui_params.get('model', '')
    
    # Scheduler
    scheduler = sui_params.get('scheduler', '')
    if scheduler:
        res['Schedule type'] = scheduler.capitalize()
    
    # Refiner/Upscale information (if used as hires fix)
    refiner_method = sui_params.get('refinermethod', '')
    refiner_upscale = sui_params.get('refinerupscale')
    refiner_upscale_method = sui_params.get('refinerupscalemethod', '')
    
    if refiner_method == 'PostApply' and refiner_upscale and refiner_upscale > 1.0:
        res['Hires upscale'] = str(refiner_upscale)
        if refiner_upscale_method:
            # Clean up the upscale method name
            upscaler = refiner_upscale_method.replace('model-', '').replace('.pt', '')
            res['Hires upscaler'] = upscaler
        
        # Refiner steps as denoising indicator (SwarmUI doesn't have exact denoising strength)
        if 'refinersteps' in sui_params:
            res['Refiner steps'] = str(sui_params['refinersteps'])
    
    # Extra metadata (optional fields)
    if 'date' in sui_extra:
        res['Generation date'] = sui_extra['date']
    
    if 'generation_time' in sui_extra:
        res['Generation time'] = sui_extra['generation_time']
    
    # SwarmUI version
    if 'swarm_version' in sui_params:
        res['SwarmUI version'] = sui_params['swarm_version']
    
    # VAE info
    if sui_params.get('automaticvae'):
        res['VAE'] = 'Automatic'
    
    # Aspect ratio
    if 'aspectratio' in sui_params:
        res['Aspect ratio'] = sui_params['aspectratio']
    
    return res

# ==================== NovelAI Parser ====================
RE_NAI_SOURCE_HASH = re.compile(r"\s+([0-9A-Fa-f]{8})$")

# Model hash -> name, for images whose Source is an internal enum name
# (e.g. "DiffusionModelMetaName.NAIv4next"). Taken from nai-meta (Miint-Sunny/nai-meta).
NAI_MODEL_HASHES = {
    'C1E1DE52': 'NovelAI Diffusion V3',
    'F6E18726': 'NovelAI Diffusion V4', '79F47848': 'NovelAI Diffusion V4', '4F49EC75': 'NovelAI Diffusion V4',
    'C1CCBA86': 'NovelAI Diffusion V4', '37442FCA': 'NovelAI Diffusion V4',
    '4BDE2A90': 'NovelAI Diffusion V4.5', '1229B44F': 'NovelAI Diffusion V4.5',
    'C02D4F98': 'NovelAI Diffusion V4.5', '5BB76870': 'NovelAI Diffusion V4.5',
    '0ADF9AB7': 'NovelAI Diffusion V5', '657484A5': 'NovelAI Diffusion V5', 'DB276663': 'NovelAI Diffusion V5',
}


def _nai_captions(caption: dict, label: str) -> str:
    """Join the base caption and character captions of a V4+ prompt object."""
    parts = []
    base = (caption.get('base_caption') or '').strip()
    if base:
        parts.append(base)
    for i, char in enumerate(caption.get('char_captions') or [], 1):
        text = (char.get('char_caption') or '').strip()
        if text:
            parts.append(f"{label} {i}: {text}")
    return "\n\n".join(parts)


def parse_novelai_parameters(info: dict) -> dict:
    """
    Parse NovelAI metadata (V3, V4, V4.5, V5).
    `info` holds the PNG text chunks: Description, Source, Comment (JSON string or dict), ...
    V4 and later keep the prompt in v4_prompt.caption; character prompts are appended as "Character N: ...".
    """
    comment = info.get('Comment') or {}
    if isinstance(comment, str):
        comment = json.loads(comment)

    v4_caption = (comment.get('v4_prompt') or {}).get('caption') or {}
    v4_negative = (comment.get('v4_negative_prompt') or {}).get('caption') or {}

    # V4+ writes the base caption to both `prompt` and v4_prompt; prefer v4_prompt to get character prompts too
    prompt = _nai_captions(v4_caption, "Character") or comment.get('prompt') or info.get('Description') or ''
    negative = _nai_captions(v4_negative, "Character") or comment.get('uc') or ''

    source = str(info.get('Source') or '')
    match = RE_NAI_SOURCE_HASH.search(source)
    model_hash = comment.get('model_hash') or (match.group(1) if match else '')
    model = comment.get('model_name') or (source[:match.start()] if match else source)
    if model_hash and (not model or model.startswith('DiffusionModel')):
        model = NAI_MODEL_HASHES.get(model_hash.upper(), model)

    res = {
        'Prompt': prompt,
        'Negative prompt': negative,
        'Seed': comment.get('seed'),
        'Steps': comment.get('steps'),
        'Sampler': comment.get('sampler'),
        'CFG scale': comment.get('scale'),
        'Schedule type': comment.get('noise_schedule'),
        'Model': model,
        'Model hash': model_hash,
    }
    if comment.get('width') and comment.get('height'):
        res['Size-1'] = comment['width']
        res['Size-2'] = comment['height']

    # Drop empty values and stringify the rest (embed field values must be non-empty strings)
    return {k: str(v) for k, v in res.items() if v not in (None, '')}


# ==================== Main Parsing Function ====================
def parse_generation_parameters(param_str: str) -> dict:
    """
    Parse generation parameters string from a Stable Diffusion image.
    Automatically detects format (WebUI or SwarmUI) and parses accordingly.
    Returns a dictionary with structured fields including:
    'Prompt', 'Negative prompt', 'Steps', 'Sampler', 'CFG scale', 'Seed', etc.
    """
    # Check if this is SwarmUI format (JSON with sui_image_params)
    if param_str.strip().startswith('{'):
        try:
            data = json.loads(param_str)
            if 'sui_image_params' in data:
                return parse_swarmui_parameters(param_str)
        except json.JSONDecodeError:
            pass  # Fall through to WebUI parser
    
    # Original WebUI parser
    res = {}
    prompt = ""
    negative_prompt = ""
    done_with_prompt = False
    
    # Split lines and separate the last line containing key-value pairs
    *lines, lastline = param_str.strip().split("\n")
    if len(RE_PARAM.findall(lastline)) < 3:
        lines.append(lastline)
        lastline = ''
    
    # Parse prompt and negative prompt lines
    for line in lines:
        line = line.strip()
        if line.startswith("Negative prompt:"):
            done_with_prompt = True
            line = line[len("Negative prompt:"):].strip()
        
        if done_with_prompt:
            negative_prompt += ("" if negative_prompt == "" else "\n") + line
        else:
            prompt += ("" if prompt == "" else "\n") + line
    
    res["Prompt"] = prompt
    res["Negative prompt"] = negative_prompt
    
    # Parse key-value parameters from the last line
    for k, v in RE_PARAM.findall(lastline):
        try:
            if v.startswith('"') and v.endswith('"'):
                v = unquote(v)
            
            size_match = RE_IMAGESIZE.match(v)
            if size_match:
                res[f"{k}-1"] = size_match.group(1)
                res[f"{k}-2"] = size_match.group(2)
            else:
                res[k] = v
        except Exception:
            print(f"Error parsing \"{k}: {v}\"")
    
    # ==================== Fill in default values ====================
    res.setdefault("Clip skip", "1")  # default Clip skip
    
    hypernet = res.get("Hypernet")
    if hypernet:
        res["Prompt"] += f"<hypernet:{hypernet}:{res.get('Hypernet strength', '1.0')}>"
    
    res.setdefault("RNG", "GPU")
    res.setdefault("Schedule type", "Automatic")
    res.setdefault("Schedule max sigma", 0)
    res.setdefault("Schedule min sigma", 0)
    res.setdefault("Schedule rho", 0)
    res.setdefault("VAE Encoder", "Full")
    res.setdefault("VAE Decoder", "Full")
    
    return res
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODELS_DIR = os.path.join(BASE_DIR, 'models')

# Keystroke directories
KEYSTROKE_DIR = os.path.join(MODELS_DIR, 'keystroke')
KEYSTROKE_GLOBAL_DIR = KEYSTROKE_DIR
KEYSTROKE_PER_USER_DIR = os.path.join(KEYSTROKE_DIR, 'user_models')

# Network directory (flat for now)
NETWORK_DIR = MODELS_DIR

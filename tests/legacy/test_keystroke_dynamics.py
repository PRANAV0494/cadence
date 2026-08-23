"""
Test Script for Keystroke Dynamics Module

Tests the keystroke feature extraction and authentication pipeline.
Run from project root: python tests/test_keystroke_dynamics.py
"""

import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import numpy as np
import pandas as pd


def test_feature_columns():
    """Test that FEATURE_COLUMNS is defined correctly."""
    from src.keystroke.feature_extractor import FEATURE_COLUMNS
    
    assert len(FEATURE_COLUMNS) == 23, f"Expected 23 features, got {len(FEATURE_COLUMNS)}"
    assert 'hold_mean' in FEATURE_COLUMNS
    assert 'flight_mean' in FEATURE_COLUMNS
    assert 'typing_speed' in FEATURE_COLUMNS
    print("✅ test_feature_columns PASSED")


def test_extract_features_basic():
    """Test feature extraction from synthetic data."""
    from src.keystroke.feature_extractor import extract_keystroke_features
    
    # Create synthetic keystroke data
    data = {
        'PARTICIPANT_ID': [1] * 10,
        'TEST_SECTION_ID': [1] * 10,
        'PRESS_TIME': list(range(0, 10000, 1000)),  # 0, 1000, 2000, ...
        'RELEASE_TIME': list(range(100, 10100, 1000)),  # 100, 1100, 2100, ...
        'KEYCODE': list(range(65, 75))  # A-J keycodes
    }
    df = pd.DataFrame(data)
    
    features = extract_keystroke_features(df, use_multiprocessing=False, show_progress=False)
    
    assert len(features) == 1, f"Expected 1 session, got {len(features)}"
    assert features['participant_id'].iloc[0] == 1
    assert features['hold_mean'].iloc[0] == 100.0  # All hold times are 100ms
    print("✅ test_extract_features_basic PASSED")


def test_get_feature_vector():
    """Test conversion to numpy feature vector."""
    from src.keystroke.feature_extractor import extract_keystroke_features, get_feature_vector
    
    data = {
        'PARTICIPANT_ID': [1] * 10,
        'TEST_SECTION_ID': [1] * 10,
        'PRESS_TIME': list(range(0, 10000, 1000)),
        'RELEASE_TIME': list(range(100, 10100, 1000)),
        'KEYCODE': list(range(65, 75))
    }
    df = pd.DataFrame(data)
    features = extract_keystroke_features(df, use_multiprocessing=False, show_progress=False)
    
    vec = get_feature_vector(features, 0)
    
    assert isinstance(vec, np.ndarray)
    assert vec.shape == (23,)
    assert not np.any(np.isnan(vec))
    print("✅ test_get_feature_vector PASSED")


def test_authenticator_load():
    """Test that KeystrokeAuthenticator loads models correctly."""
    from src.keystroke.authenticator import KeystrokeAuthenticator
    
    models_dir = PROJECT_ROOT / "models"
    if not models_dir.exists():
        print("⚠️  test_authenticator_load SKIPPED (models/ not found)")
        return
    
    try:
        auth = KeystrokeAuthenticator(models_dir=models_dir)
        assert auth.xgb_model is not None
        assert auth.scaler is not None
        assert auth.imputer is not None
        assert auth.label_encoder is not None
        assert len(auth.feature_columns) == 23
        print("✅ test_authenticator_load PASSED")
    except FileNotFoundError as e:
        print(f"⚠️  test_authenticator_load SKIPPED ({e})")


def test_identify_user():
    """Test user identification with dummy data."""
    from src.keystroke.authenticator import KeystrokeAuthenticator
    
    models_dir = PROJECT_ROOT / "models"
    if not models_dir.exists():
        print("⚠️  test_identify_user SKIPPED (models/ not found)")
        return
    
    try:
        auth = KeystrokeAuthenticator(models_dir=models_dir)
        
        # Create dummy feature vector
        vec = np.zeros((1, 23))
        
        user_id = auth.identify_user(vec)
        assert user_id is not None
        print(f"✅ test_identify_user PASSED (identified: {user_id})")
    except FileNotFoundError as e:
        print(f"⚠️  test_identify_user SKIPPED ({e})")


def test_is_anomaly():
    """Test anomaly detection."""
    from src.keystroke.authenticator import KeystrokeAuthenticator
    
    models_dir = PROJECT_ROOT / "models"
    if not models_dir.exists():
        print("⚠️  test_is_anomaly SKIPPED (models/ not found)")
        return
    
    try:
        auth = KeystrokeAuthenticator(models_dir=models_dir)
        
        vec = np.zeros((1, 23))
        user_id = auth.identify_user(vec)
        
        score, is_anom = auth.is_anomaly(user_id, vec)
        assert isinstance(score, (float, np.floating))
        assert isinstance(is_anom, (bool, np.bool_))
        print(f"✅ test_is_anomaly PASSED (score={score:.4f}, anomaly={is_anom})")
    except FileNotFoundError as e:
        print(f"⚠️  test_is_anomaly SKIPPED ({e})")


def test_full_authentication():
    """Test full authentication pipeline."""
    from src.keystroke.authenticator import KeystrokeAuthenticator
    
    models_dir = PROJECT_ROOT / "models"
    if not models_dir.exists():
        print("⚠️  test_full_authentication SKIPPED (models/ not found)")
        return
    
    try:
        auth = KeystrokeAuthenticator(models_dir=models_dir)
        
        vec = np.zeros((1, 23))
        result = auth.authenticate(vec)
        
        assert 'user_id' in result
        assert 'confidence' in result
        assert 'anomaly_score' in result
        assert 'is_anomaly' in result
        assert 'authenticated' in result
        print(f"✅ test_full_authentication PASSED (auth={result['authenticated']})")
    except FileNotFoundError as e:
        print(f"⚠️  test_full_authentication SKIPPED ({e})")


def run_all_tests():
    """Run all tests."""
    print("=" * 60)
    print("Keystroke Dynamics Module Tests")
    print("=" * 60)
    print()
    
    test_feature_columns()
    test_extract_features_basic()
    test_get_feature_vector()
    test_authenticator_load()
    test_identify_user()
    test_is_anomaly()
    test_full_authentication()
    
    print()
    print("=" * 60)
    print("All tests completed!")
    print("=" * 60)


if __name__ == "__main__":
    run_all_tests()

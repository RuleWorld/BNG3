import sys
sys.meta_path = [f for f in sys.meta_path if 'editable' not in type(f).__module__.lower() and 'skbc' not in type(f).__module__.lower()]

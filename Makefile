tests:
	PYTHONPATH=$$(pwd) pipenv run pytest . -s

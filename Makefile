tests:
	PYTHONPATH=$$(pwd) pipenv run pytest . -s --reruns 3 --reruns-delay 1

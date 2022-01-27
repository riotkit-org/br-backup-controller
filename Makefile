tests:
	PYTHONPATH=$$(pwd) pipenv run pytest . -s --reruns 5 --reruns-delay 5

all:

test: projectionist.py config-local.yaml
	./projectionist.py -vf config-local.yaml

clean:
	rm -fr __pycache__ projectionist.out

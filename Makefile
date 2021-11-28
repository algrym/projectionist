all:

test: projectionist.py config-local.yaml
	./projectionist.py -vf config-local.yaml | tee projectionist.out

clean:
	rm -fr __pycache__ projectionist.out

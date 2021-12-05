all:

run: install projectionist.py config-local.yaml
	systemctl --user restart projectionist

stop:
	systemctl --user stop projectionist

clean:
	rm -fr __pycache__ projectionist.out

install: install_service

install_service: projectionist.service
	mkdir -p ~/.config/systemd/user
	cp -v projectionist.service ~/.config/systemd/user/
	systemctl --user daemon-reload

list_serial_ports:
	python -m serial.tools.list_ports

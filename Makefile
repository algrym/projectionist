all:

run: install projectionist.py config-local.yaml
	systemctl --user restart projectionist

clean:
	rm -fr __pycache__ projectionist.out

install: install_service

install_service: projectionist.service
	mkdir -p ~/.config/systemd/user
	cp -v projectionist.service ~/.config/systemd/user/
	systemctl --user daemon-reload

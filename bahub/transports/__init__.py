"""
Transport
=========

Abstraction that allows end-user to select if the backup should be done via local shell, ssh, docker,
kubernetes container etc.

Any transport can be implemented that will take a command, then process and properly output the result.
"""

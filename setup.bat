virtualenv %appdata%\bhmfg\stripe\env

call %appdata%\bhmfg\stripe\env\Scripts\activate.bat
call pip install -r \\fs5\Users\Derek\git\stripe-card-terminal\requirements.txt

type NUL > %appdata%\bhmfg\stripe\terminal.bat
ECHO call %appdata%\bhmfg\stripe\env\Scripts\activate.bat >> %appdata%\bhmfg\stripe\terminal.bat
ECHO pushd \\fs5\Users\Derek\git\stripe-card-terminal >> %appdata%\bhmfg\stripe\terminal.bat
ECHO start pythonw main.pyw >> %appdata%\bhmfg\stripe\terminal.bat
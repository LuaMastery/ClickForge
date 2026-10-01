# Licenças de terceiros

O ClickForge em si é licenciado sob a [Licença MIT](LICENSE) (© 2026 Rhuan De Cillo Silva). O `.exe` distribuído embute as bibliotecas abaixo, cada uma com sua própria licença. Todas são de código aberto e permitem uso e redistribuição gratuitos.

| Componente | Versão usada | Licença | Para que serve |
| --- | --- | --- | --- |
| [Python](https://www.python.org/) (interpretador e biblioteca padrão, incluindo Tcl/Tk) | 3.11 (build oficial) | PSF License; Tcl/Tk: licença BSD-like | Linguagem e interface gráfica |
| [pynput](https://github.com/moses-palmer/pynput) | 1.8.x | LGPL-3.0 | Tipos de teclas/botões do mouse |
| [pystray](https://github.com/moses-palmer/pystray) | 0.19.x | LGPL-3.0 | Ícone na bandeja do sistema |
| [Pillow](https://github.com/python-pillow/Pillow) | 12.x | MIT-CMU (HPND) | Desenho de ícones e imagens |
| [six](https://github.com/benjaminp/six) (dependência do pynput) | 1.17 | MIT | Compatibilidade |
| [PyInstaller](https://pyinstaller.org/) (apenas na compilação) | 6.x | GPL-2.0-or-later **com exceção** que permite distribuir programas gerados sob qualquer licença | Gera o `.exe` |

## Sobre as bibliotecas LGPL (pynput e pystray)

A LGPL-3.0 permite usar a biblioteca dentro de um programa com outra licença, desde que o usuário possa substituí-la por uma versão modificada. Isso é atendido aqui: o código-fonte completo do ClickForge e o [`requirements.txt`](requirements.txt) são públicos, então qualquer pessoa pode instalar outra versão dessas bibliotecas e recompilar o programa seguindo as instruções do [README](README.md). Os textos completos estão em:

- LGPL-3.0: <https://www.gnu.org/licenses/lgpl-3.0.html>
- GPL-3.0 (que a LGPL complementa): <https://www.gnu.org/licenses/gpl-3.0.html>

## Sobre o PyInstaller

O bootloader do PyInstaller é GPL, mas acompanha uma exceção expressa que permite usá-lo para gerar e distribuir executáveis sob qualquer licença, inclusive a MIT. Veja: <https://pyinstaller.org/en/stable/license.html>

---

*Este arquivo é um resumo informativo, não aconselhamento jurídico. Em caso de divergência, valem os textos originais de cada licença.*

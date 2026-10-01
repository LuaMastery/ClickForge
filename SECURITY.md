# Segurança e transparência

O ClickForge é 100% código aberto: tudo o que o programa faz está em um único arquivo legível, [`clickforge.py`](clickforge.py). Esta página explica o que ele faz no seu computador, por que o Windows Defender às vezes reclama dele e como você mesmo pode conferir.

## O que o ClickForge faz (e não faz)

| Comportamento | Para que serve | Observação |
| --- | --- | --- |
| Hooks globais de teclado/mouse (`SetWindowsHookEx`) | Detectar o **atalho** de ligar/desligar e saber quando o clique é seu ou do próprio app | Nada do que você digita é guardado ou enviado. O gravador de macro só registra **enquanto você aperta "Gravar"** e salva só na sua máquina. |
| Gerar cliques/teclas (`SendInput`) | É o próprio autoclicker | — |
| Ler a janela em foco e a cor de um pixel | Recursos opcionais: perfil por janela e gatilho por cor | Lê só o necessário, localmente. |
| Chave `Run` do registro (usuário atual) | "Iniciar com o Windows" | **Desligado por padrão**; só liga se você marcar a opção, e desliga se desmarcar. |
| Rede | Verificar/baixar atualização | Só fala com `api.github.com` e `github.com` (a release do repositório). **Sem telemetria, sem anúncios, sem contas.** |
| Porta local `127.0.0.1` | Impedir abrir duas cópias do app | Só aceita conexões da própria máquina. |
| Arquivos gravados | Configurações, perfis e estatísticas | Em `%APPDATA%\ClickForge-Autoclicker`. |

O que o programa **não** faz: não envia dados seus para lugar nenhum, não captura tela, não abre portas para a internet, não instala outros programas, não altera configurações do sistema além da opção opcional acima.

## Por que o Windows Defender pode alertar

Quase sempre é **falso positivo**, e há motivos objetivos:

1. **Empacotamento com PyInstaller.** O `.exe` é um programa Python "embutido". Ferramentas de segurança desconfiam desse formato porque muito malware também o usa.
2. **Comportamento parecido com keylogger.** Um autoclicker com atalho global precisa de hooks de teclado/mouse — a mesma API que programas maliciosos usam. A heurística não distingue a intenção.
3. **Arquivo novo, sem reputação e sem assinatura digital.** O SmartScreen/Defender desconfia de qualquer executável pouco baixado e sem certificado de editor. Certificados de assinatura de código são pagos, e o projeto ainda não tem um.
4. **Atualizador automático.** Baixar um `.exe` e trocá-lo por um script auxiliar também é padrão que heurísticas observam.

### O que o projeto já faz para reduzir isso

- O `.exe` das releases é compilado **dentro do GitHub Actions**, a partir do código público da tag — não é enviado do computador de ninguém ([`release.yml`](.github/workflows/release.yml)).
- Sem compressão UPX (`--noupx`), que é um gatilho clássico de antivírus.
- O executável traz metadados reais (editor, descrição, versão, licença) — veja em *Propriedades → Detalhes*.
- Cada release traz o **SHA-256** (`ClickForge.exe.sha256`) e uma **atestação de procedência assinada pelo GitHub**.
- O atualizador do app **confere o SHA-256** antes de aplicar qualquer atualização e descarta o arquivo se não bater.

## Como você mesmo confere

**1. Hash do arquivo** (deve ser igual ao do `ClickForge.exe.sha256` da release):

```powershell
Get-FileHash .\ClickForge.exe -Algorithm SHA256
```

**2. Procedência** (prova que o arquivo foi gerado pelo workflow deste repositório, com GitHub CLI):

```powershell
gh attestation verify .\ClickForge.exe --repo LuaMastery/ClickForge
```

**3. Compile você mesmo** (sem confiar em ninguém):

```powershell
pip install -r requirements.txt pyinstaller
python make_version_info.py
python -m PyInstaller --onefile --windowed --noupx --name ClickForge --icon icon.ico --version-file version_info.txt clickforge.py
```

**4. Ou rode direto do código-fonte**, sem `.exe` nenhum: `pip install -r requirements.txt` e `python clickforge.py`.

**5.** Envie o arquivo ao [VirusTotal](https://www.virustotal.com/) para ver o resultado de dezenas de antivírus. Um ou outro alerta genérico (por exemplo `Trojan:Win32/Wacatac`, `Program:Win32/...`) em arquivos PyInstaller é típico de falso positivo.

## Se o Defender bloquear mesmo assim

- **Relatar como falso positivo à Microsoft** (é o que realmente resolve com o tempo): <https://www.microsoft.com/en-us/wdsi/filesubmission> — escolha "Software developer" e envie o `.exe` da release.
- Se você baixou da [página oficial de Releases](../../releases) e conferiu o hash, pode restaurar o arquivo em *Segurança do Windows → Proteção contra vírus e ameaças → Histórico de proteção* e permitir. Só faça isso depois de conferir o hash.

## Reportar uma vulnerabilidade

Abra uma [issue](../../issues) (ou, se for sensível, use *Security → Report a vulnerability* na página do repositório).

## Licença

O ClickForge é distribuído sob a **Licença MIT** ([`LICENSE`](LICENSE)). As bibliotecas que ele usa e suas licenças estão em [`THIRD_PARTY_LICENSES.md`](THIRD_PARTY_LICENSES.md).

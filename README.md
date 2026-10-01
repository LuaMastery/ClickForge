# ClickForge

Um autoclicker leve para Windows, feito em Python/Tkinter — configurável, com atalhos de teclado ou mouse, múltiplos cliques independentes rodando ao mesmo tempo, e sem precisar instalar Python para usar (roda como `.exe` único).

## Funcionalidades

- **Clique único ou "segurar pressionado"**, com botão do mouse (esquerdo, direito, meio, mouse 4/5) ou uma tecla do teclado.
- **Atalho global configurável** — qualquer tecla ou botão do mouse, em modo "alternar" (aperta pra ligar/desligar) ou "segurar para ativar" (mantém pressionado pra clicar, solta pra parar). Funciona até quando o mesmo botão usado como atalho é o que está sendo clicado, sem travar.
- **Tecla de parada de emergência** independente do atalho principal.
- **Múltiplos autocliques em paralelo** (aba "Múltiplos"): crie vários, cada um com sua própria ação, intervalo e gatilho, todos rodando ao mesmo tempo.
- **Intervalo configurável** (h/min/s/ms) com variação aleatória opcional, posição fixa ou atual do mouse (com variação aleatória de posição e indicador visual na tela), repetição por número de cliques ou duração.
- **Perfis** para salvar e recarregar combinações de configuração.
- **Roda em segundo plano** — minimiza para a bandeja do sistema em vez de fechar; pode iniciar junto com o Windows e, opcionalmente, já abrir oculto.
- **Sequência de posições**: clica em vários pontos da tela em ordem, em loop.
- **Gravador de macros**: grave cliques e teclas com o tempo entre eles e reproduza (com loop opcional).
- **Perfil automático por janela ativa**: troca de perfil sozinho conforme o programa em foco.
- **Agendamento**: iniciar em um horário definido ou após o computador ficar ocioso.
- **Gatilho por cor de pixel**: só clica quando a cor em um ponto da tela bate com a escolhida.
- **Estatísticas** de cliques (total e últimos 7 dias), **tema claro/escuro**, **som personalizado**, **exportar/importar perfis** e aba de **diagnóstico**.
- **Janela redimensionável** e configurações salvas automaticamente.
- **Atualização automática**: verifica releases novas no GitHub e aplica sozinho na próxima vez que o app for fechado.

## Como usar

Baixe o `.exe` mais recente em [Releases](../../releases) e execute — não precisa instalar nada.

## Rodando a partir do código-fonte

Requer Python 3.10+ no Windows.

```bash
pip install -r requirements.txt
python clickforge.py
```

## Gerando o .exe

```bash
pip install pyinstaller
python -m PyInstaller --onefile --windowed --name ClickForge --icon icon.ico clickforge.py
```

O executável fica em `dist/ClickForge.exe`.

## Contribuindo

Pull requests são bem-vindos. O projeto é um único arquivo (`clickforge.py`) por simplicidade — mantenha novas funcionalidades consistentes com o estilo existente (Tkinter puro, sem dependências pesadas).

## Licença

[MIT](LICENSE) — use, modifique e redistribua livremente.

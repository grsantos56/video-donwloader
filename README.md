# MediaFlow - Gerenciador e Baixador de Vídeos Multimídia

O **MediaFlow** é um MVP de um site moderno, limpo e responsivo projetado para baixar vídeos e áudios das principais redes sociais (YouTube, TikTok, Instagram, Twitter/X, Facebook, e muito mais) em diversas qualidades de forma rápida e segura.

## 🚀 Funcionalidades

- **Ampla Compatibilidade:** Suporta o download de links do YouTube, TikTok, Instagram, Twitter/X e Facebook de maneira integrada.
- **Escolha de Formatos & Qualidades:**
  - Baixe vídeos completos ou apenas a faixa de áudio.
  - Exibição de todas as resoluções disponíveis (desde 144p até 1080p Full HD e 4K/2160p).
  - Organização visual das qualidades agrupadas por tipo de arquivo (MP4, WEBM, M4A, etc.).
- **Processamento de Alta Qualidade (Mesclagem com FFmpeg):**
  - Integração dinâmica com o **FFmpeg** no servidor.
  - Se a qualidade de vídeo desejada for dividida (sem áudio nativo), a aplicação faz o download do vídeo e do melhor áudio separadamente e realiza a mesclagem automática no servidor, garantindo um arquivo de alta definição funcional com som.
- **Downloads Seguros e Rápidos:**
  - Armazenamento temporário seguro em cache local no servidor para evitar corrupção de fluxo no Windows.
  - Liberação progressiva do arquivo com cabeçalho `Content-Length` (exibindo a barra de progresso real do download no navegador).
  - Limpeza automática: os arquivos temporários são deletados imediatamente após o término do download.
- **Interface Premium e Moderna:**
  - Design limpo e responsivo baseado em Tailwind CSS e Lucide Icons (sem o uso de emojis, focando em ícones elegantes).
  - Ticker de letreiro infinito estilizado com os logos SVG oficiais no topo da tela.
  - Alternador de temas dinâmico (Tema Claro / Tema Escuro) persistido no navegador.
- **Pronto para SEO:**
  - Meta tags configuradas (Open Graph e Twitter Cards) para indexação rápida e pré-visualizações ricas em compartilhamentos de links.
  - Ícone de favicon personalizado.

## 🛠️ Tecnologias Utilizadas

- **Backend:** Python 3 (Flask) + `yt-dlp` + subprocessos.
- **Processamento de Mídia:** FFmpeg (instalado via winget).
- **Frontend:** HTML5 + Tailwind CSS + Vanilla JS + Lucide Icons.
- **Versionamento:** Git (com repositório público configurado).

## 📋 Pré-requisitos

Para rodar e testar o projeto localmente, certifique-se de ter instalado:
1. **Python 3.10+**
2. **Node.js** (necessário para a resolução de desafios JavaScript pelo solucionador do `yt-dlp`).
3. **FFmpeg** (caso utilize Windows, a aplicação tenta localizá-lo automaticamente no diretório do winget, mas garanta que ele esteja instalado ou no PATH do sistema).

## 🔧 Instalação e Execução

1. **Clonar o Repositório:**
   ```bash
   git clone https://github.com/grsantos56/video-donwloader.git
   cd "gerenciador de downloads"
   ```

2. **Criar e Ativar Ambiente Virtual:**
   ```powershell
   python -m venv venv
   .\venv\Scripts\activate
   ```

3. **Instalar Dependências:**
   ```powershell
   pip install -r requirements.txt
   ```

4. **Executar o Servidor:**
   ```powershell
   python app.py
   ```

5. **Acessar no Navegador:**
   Abra seu navegador em [http://127.0.0.1:5000](http://127.0.0.1:5000).

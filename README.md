# 🍺 Homebrew Manager

A modern, web-based GUI for managing Homebrew packages on macOS and Linux. This application provides an intuitive interface for installing, updating, upgrading, and managing your Homebrew formulae and casks with real-time streaming output and comprehensive package information.

## ✨ Features

### 📦 Package Management
- **View Installed Packages**: Browse all installed formulae and casks with descriptions and versions
- **Update Detection**: See which packages are outdated and need upgrading
- **Bulk Operations**: Select multiple packages for batch upgrade operations
- **Search & Install**: Search for new packages and install them directly from the interface
- **Uninstall Packages**: Remove packages with a single click

### 🔍 Advanced Features
- **Orphaned Package Detection**: Identify packages that were installed as dependencies but are no longer needed
- **Deprecated Package Alerts**: Get notified about deprecated or disabled packages
- **Real-time Streaming**: Watch package operations in real-time with live output
- **Sudo Integration**: Seamless handling of operations requiring administrator privileges
- **Package Information**: Detailed information about each package including descriptions, versions, and homepages

### 🎨 Modern Interface
- **Dark Theme**: Beautiful dark mode interface optimized for long usage sessions
- **Responsive Design**: Works perfectly on desktop and tablet devices
- **Activity Panel**: Real-time activity log showing all operations
- **Toast Notifications**: Instant feedback for user actions
- **Keyboard Shortcuts**: Efficient navigation and operation shortcuts

## 🚀 Quick Start

### Prerequisites

Before using Homebrew Manager, you need to have the following installed:

1. **Python 3.7+** (included with macOS, or install via Homebrew)
2. **Homebrew** (the package manager this app manages)

### Installation

#### For macOS Users

1. **Install Homebrew** (if not already installed):
   ```bash
   # Install Homebrew
   /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
   
   # Follow the post-installation instructions for your shell
   ```

2. **Install Python** (if not already installed):
   ```bash
   # Check if Python is installed
   python3 --version
   
   # If not installed, install via Homebrew
   brew install python
   ```

3. **Clone and Run Homebrew Manager**:
   ```bash
   # Clone the repository
   git clone https://github.com/yourusername/Homebrew-Manager.git
   cd Homebrew-Manager
   
   # Run the application
   python3 server.py
   ```

4. **Open in Browser**:
   - Navigate to `http://127.0.0.1:8765` in your web browser
   - The application will automatically detect your Homebrew installation

#### For Linux Users (with Homebrew)

1. **Install Python**:
   ```bash
   # Ubuntu/Debian
   sudo apt update
   sudo apt install python3 python3-pip
   
   # CentOS/RHEL/Fedora
   sudo dnf install python3 python3-pip  # or yum for older versions
   ```

2. **Install Homebrew for Linux**:
   ```bash
   # Install Homebrew
   /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
   
   # Add to PATH (follow the instructions provided by the installer)
   eval "$(/home/linuxbrew/.linuxbrew/bin/brew shellenv)"
   ```

3. **Clone and Run Homebrew Manager**:
   ```bash
   # Clone the repository
   git clone https://github.com/yourusername/Homebrew-Manager.git
   cd Homebrew-Manager
   
   # Run the application
   python3 server.py
   ```

4. **Open in Browser**:
   - Navigate to `http://127.0.0.1:8765` in your web browser

## 📖 Usage Guide

### Getting Started

1. **Launch the Application**:
   - Run `python3 server.py` in the project directory
   - Open your browser to `http://127.0.0.1:8765`

2. **Initial Setup**:
   - The app will automatically detect your Homebrew installation
   - If Homebrew needs updating, you'll see an "Update Homebrew" button
   - Click it to update Homebrew's package database

### Main Interface

The application has four main tabs:

#### 📦 Packages Tab
- **Outdated Packages**: View and upgrade packages that have newer versions available
- **All Installed Packages**: Browse, search, and manage all installed packages
- **Bulk Operations**: Select multiple packages for batch upgrades

#### 🗑️ Orphaned Tab
- View packages that were installed as dependencies but are no longer needed
- These can be safely uninstalled to free up space

#### ⚠️ Deprecated Tab
- See packages that are deprecated or disabled
- Get information about why they're deprecated and alternatives

#### 🔍 Search Tab
- Search for new packages to install
- Browse formulae and casks with descriptions
- Install packages directly from search results

### Common Operations

#### Updating Homebrew
- Click the "Update Homebrew" button in the header when available
- This updates Homebrew's package database

#### Upgrading Packages
1. **Individual Upgrade**: Click the upgrade button next to any outdated package
2. **Bulk Upgrade**: 
   - Select multiple packages using checkboxes
   - Click "Upgrade Selected" to upgrade all at once
3. **Upgrade All**: Use the bulk selection to upgrade all outdated packages

#### Installing New Packages
1. Go to the Search tab
2. Enter the package name in the search box
3. Browse results and click "Install" on desired packages

#### Uninstalling Packages
- Click the uninstall button next to any installed package
- Confirm the action in the dialog

### Sudo Operations

Some operations require administrator privileges:

1. **Automatic Detection**: The app detects when sudo is needed
2. **Current Workaround**: When sudo is required, enter your password in the terminal where you launched the application
3. **Future Enhancement**: In-app sudo password handling is planned (see TODO section)

### Activity Panel

The activity panel (bottom-right) shows:
- Real-time operation logs
- Success/error messages
- Progress updates for long-running operations

## 🔧 Configuration

### Environment Variables

- `PORT`: Set the port number (default: 8765)
  ```bash
  PORT=8080 python3 server.py
  ```

### Custom Homebrew Path

The application automatically detects Homebrew installations in common locations:
- `/opt/homebrew/bin/brew` (Apple Silicon Macs)
- `/usr/local/bin/brew` (Intel Macs)
- `/home/linuxbrew/.linuxbrew/bin/brew` (Linux)

If Homebrew is installed elsewhere, ensure it's in your `PATH`.

## 🛠️ Technical Details

### Architecture
- **Backend**: Python 3.7+ with built-in HTTP server
- **Frontend**: Vanilla JavaScript with modern CSS
- **Communication**: RESTful API with Server-Sent Events (SSE) for real-time updates
- **Package Management**: Direct integration with Homebrew CLI

### API Endpoints

The application provides a REST API for programmatic access:

- `GET /api/health` - Check Homebrew status
- `GET /api/summary` - Get overview of all packages
- `GET /api/outdated` - List outdated packages
- `GET /api/installed` - List all installed packages
- `GET /api/search?q=<query>` - Search for packages
- `POST /api/install` - Install a package
- `POST /api/uninstall` - Uninstall a package
- `POST /api/upgrade` - Upgrade packages

### Streaming Operations

Long-running operations use Server-Sent Events for real-time feedback:
- `GET /api/update_stream` - Stream Homebrew update progress
- `GET /api/upgrade_stream` - Stream package upgrade progress
- `GET /api/install_stream` - Stream package installation progress

## 🐛 Troubleshooting

### Common Issues

1. **"Homebrew not found" Error**:
   - Ensure Homebrew is installed and in your PATH
   - Try running `brew --version` in terminal to verify

2. **Permission Errors**:
   - Some operations require sudo privileges
   - Enter your password in the terminal where you launched the application when prompted

3. **Port Already in Use**:
   - Change the port: `PORT=8080 python3 server.py`
   - Or kill the existing process using the port

4. **Python Not Found**:
   - Install Python 3.7+: `brew install python`
   - Ensure `python3` command is available

### Debug Mode

For troubleshooting, you can run with verbose output:
```bash
python3 -u server.py 2>&1 | tee homebrew-manager.log
```

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

### Development Setup

1. Clone the repository
2. Make your changes
3. Test thoroughly with different Homebrew configurations
4. Submit a pull request

### Code Style

- Follow PEP 8 for Python code
- Use meaningful variable and function names
- Add comments for complex logic
- Test your changes before submitting

## 📝 License

This project is licensed under the MIT License - see the LICENSE file for details.

## 🙏 Acknowledgments

- Built for the Homebrew community
- Inspired by the need for a better GUI for Homebrew management
- Uses modern web technologies for a responsive experience

---

## 🚧 TODO Features

### High Priority
- [ ] **Package Dependencies View**: Show dependency trees for installed packages
- [ ] **Batch Uninstall**: Allow selecting multiple packages for bulk uninstallation
- [ ] **Package Categories**: Organize packages by category (development, utilities, etc.)
- [ ] **Export/Import**: Export package lists and import them on other systems
- [ ] **Backup/Restore**: Create backups of current package state
- [ ] **Sudo Password Integration**: Fix in-app sudo password handling for seamless administrative operations

### Medium Priority
- [ ] **Custom Taps Support**: Manage custom Homebrew taps
- [ ] **Package History**: Track installation/uninstallation history
- [ ] **Disk Usage Analysis**: Show disk space used by packages
- [ ] **Update Scheduling**: Schedule automatic updates
- [ ] **Notification System**: Desktop notifications for updates
- [ ] **Keyboard Shortcuts**: Add more keyboard shortcuts for power users

### Low Priority
- [ ] **Theme Support**: Light/dark theme toggle
- [ ] **Multi-language Support**: Internationalization
- [ ] **Plugin System**: Allow third-party plugins
- [ ] **Statistics Dashboard**: Usage statistics and analytics
- [ ] **Package Recommendations**: Suggest packages based on usage patterns
- [ ] **Integration APIs**: Webhook support for CI/CD integration

### Technical Improvements
- [ ] **Performance Optimization**: Faster package listing and search
- [ ] **Offline Mode**: Basic functionality when Homebrew is unavailable
- [ ] **Configuration File**: User preferences and settings persistence
- [ ] **Logging System**: Comprehensive logging for debugging
- [ ] **Unit Tests**: Comprehensive test coverage
- [ ] **Docker Support**: Containerized deployment option

### User Experience
- [ ] **Onboarding Tour**: Interactive tutorial for new users
- [ ] **Keyboard Navigation**: Full keyboard accessibility
- [ ] **Mobile Responsiveness**: Better mobile experience
- [ ] **Drag & Drop**: Drag packages between lists
- [ ] **Search Filters**: Advanced search with filters (formula/cask, installed/available)
- [ ] **Package Comparison**: Compare versions and features between packages

---

**Note**: This application is designed to work with Homebrew on macOS and Linux systems. It provides a modern, user-friendly interface for managing your Homebrew packages without needing to remember complex command-line syntax. 

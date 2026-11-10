// HRAutomation.exe - the one file a client double-clicks after unzipping (Part 28).
//
//   - Asks Windows for administrator rights (services and Program Files need them).
//   - Not installed yet: starts the setup screen (runtime\python\python.exe -m app.platform.install.wizard)
//     which opens in the browser and does everything else.
//   - Already installed: makes sure the services run and opens HR Automation in the browser.
//
// Build (any OS):  GOOS=windows GOARCH=amd64 go build -o HRAutomation.exe .
// Standard library only: no downloads needed to build it.
package main

import (
	"bufio"
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"syscall"
	"unsafe"
)

var (
	shell32          = syscall.NewLazyDLL("shell32.dll")
	procIsUserAdmin  = shell32.NewProc("IsUserAnAdmin")
	procShellExecute = shell32.NewProc("ShellExecuteW")
)

func isAdmin() bool {
	r, _, _ := procIsUserAdmin.Call()
	return r != 0
}

func elevate(exe string, args []string, dir string) error {
	verb, _ := syscall.UTF16PtrFromString("runas")
	file, _ := syscall.UTF16PtrFromString(exe)
	params, _ := syscall.UTF16PtrFromString(strings.Join(args, " "))
	cwd, _ := syscall.UTF16PtrFromString(dir)
	r, _, _ := procShellExecute.Call(0, uintptr(unsafe.Pointer(verb)), uintptr(unsafe.Pointer(file)),
		uintptr(unsafe.Pointer(params)), uintptr(unsafe.Pointer(cwd)), 1)
	if r <= 32 {
		return fmt.Errorf("Windows did not allow administrator rights (code %d)", r)
	}
	return nil
}

func openBrowser(url string) {
	_ = exec.Command("rundll32", "url.dll,FileProtocolHandler", url).Start()
}

func pause() {
	fmt.Println("\nPress Enter to close this window.")
	bufio.NewReader(os.Stdin).ReadString('\n')
}

type installed struct {
	Version    string `json:"version"`
	InstallDir string `json:"install_dir"`
	URL        string `json:"url"`
}

func readVersion(dir string) string {
	b, err := os.ReadFile(filepath.Join(dir, "VERSION.txt"))
	if err != nil {
		return "dev"
	}
	return strings.TrimSpace(string(b))
}

func main() {
	exe, _ := os.Executable()
	bundle := filepath.Dir(exe)
	if !isAdmin() {
		if err := elevate(exe, os.Args[1:], bundle); err != nil {
			fmt.Println("HR Automation setup needs administrator rights:", err)
			pause()
		}
		return
	}
	fmt.Println("HR Automation", readVersion(bundle))

	info := filepath.Join(os.Getenv("ProgramData"), "HRAutomation", "installed.json")
	if b, err := os.ReadFile(info); err == nil {
		var in installed
		if json.Unmarshal(b, &in) == nil && in.URL != "" {
			fmt.Println("HR Automation is already installed in", in.InstallDir)
			if v := readVersion(bundle); v != in.Version && v != "dev" {
				fmt.Printf("This package is version %s; the installed one is %s. Run setup again to upgrade: %s --setup\n", v, in.Version, exe)
				if len(os.Args) < 2 || os.Args[1] != "--setup" {
					pause()
					return
				}
			} else {
				for _, svc := range []string{"HRAutomation-PostgreSQL", "HRAutomation-App"} {
					_ = exec.Command("sc", "start", svc).Run()
				}
				fmt.Println("Opening", in.URL)
				openBrowser(in.URL)
				return
			}
		}
	}

	python := filepath.Join(bundle, "runtime", "python", "python.exe")
	backend := filepath.Join(bundle, "app", "backend")
	if _, err := os.Stat(python); err != nil {
		fmt.Println("This folder is incomplete (runtime\\python is missing). Unzip the whole HR Automation zip file and run HRAutomation.exe from it.")
		pause()
		return
	}
	fmt.Println("Starting the setup screen in your browser...")
	cmd := exec.Command(python, "-m", "app.platform.install.wizard", "--bundle", bundle)
	cmd.Dir = backend
	cmd.Env = append(os.Environ(), "PYTHONIOENCODING=utf-8", "PYTHONUTF8=1")
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	if err := cmd.Run(); err != nil {
		fmt.Println("Setup stopped:", err)
		pause()
		return
	}
	fmt.Println("Setup finished. You can close this window.")
}

//! Núcleo nativo de AERO Player (fase R1 de docs/RUST.md).
//!
//! Hace en Rust lo que más trabaja con miles de archivos: listar una carpeta y clasificar cada entrada,
//! sumar el tamaño de una carpeta y buscar por nombre en carpetas enteras. Las tablas de clasificación
//! (extensión → categoría y firmas de los primeros bytes) vienen de `aero/core/filetypes.py` con
//! `configure()`, así que Python y Rust nunca se contradicen. El GIL se libera mientras se recorre el
//! disco: la interfaz sigue fluida.

mod tags;

use pyo3::exceptions::PyOSError;
use pyo3::prelude::*;
use std::collections::HashMap;
use std::fs;
use std::io::{Read, Seek, SeekFrom};
use std::path::{Path, PathBuf};
use std::sync::RwLock;
use std::time::{Duration, Instant, UNIX_EPOCH};
use unicode_normalization::char::is_combining_mark;
use unicode_normalization::UnicodeNormalization;

#[cfg(windows)]
use std::os::windows::fs::MetadataExt;

const FILE_ATTRIBUTE_HIDDEN: u32 = 0x2;
const FILE_ATTRIBUTE_SYSTEM: u32 = 0x4;

struct Tables {
    by_ext: HashMap<String, String>,
    magic: Vec<(usize, Vec<u8>, String)>,
}

static TABLES: RwLock<Option<Tables>> = RwLock::new(None);

/// Carga las tablas de `filetypes.py`: {".mp4": "video", …} y [(desplazamiento, bytes, categoría), …].
#[pyfunction]
fn configure(by_ext: HashMap<String, String>, magic: Vec<(usize, Vec<u8>, String)>) {
    *TABLES.write().unwrap() = Some(Tables { by_ext, magic });
}

fn ext_of(name: &str) -> String {
    // Igual que filetypes.ext_of: el punto debe ir después de algún carácter que no sea separador.
    match name.rfind('.') {
        Some(dot) => {
            let sep = name.rfind(|c| c == '/' || c == '\\').map(|i| i as isize).unwrap_or(-1);
            if (dot as isize) <= sep + 1 {
                String::new()
            } else {
                name[dot..].to_lowercase()
            }
        }
        None => String::new(),
    }
}

fn by_extension(t: &Tables, name: &str, is_dir: bool) -> String {
    if is_dir {
        return "folder".into();
    }
    t.by_ext.get(&ext_of(name)).cloned().unwrap_or_else(|| "unknown".into())
}

/// Misma lógica que `filetypes.sniff`: firma de 64 bytes, RIFF, ftyp, «CD001» en 0x8001 y texto plano.
fn sniff(t: &Tables, path: &Path, size: u64) -> String {
    let mut head = [0u8; 64];
    let n = match fs::File::open(path).and_then(|mut f| f.read(&mut head)) {
        Ok(n) => n,
        Err(_) => return "unknown".into(),
    };
    let head = &head[..n];
    if head.is_empty() {
        return "unknown".into();
    }
    for (off, sig, cat) in &t.magic {
        if head.len() >= off + sig.len() && &head[*off..off + sig.len()] == sig.as_slice() {
            return cat.clone();
        }
    }
    if head.len() >= 12 && &head[..4] == b"RIFF" {
        return match &head[8..12] {
            b"WAVE" => "audio",
            b"AVI " => "video",
            b"WEBP" => "image",
            _ => "unknown",
        }
        .into();
    }
    if head.len() >= 12 && &head[4..8] == b"ftyp" {
        let brand = &head[8..12];
        if brand == b"M4A " || brand == b"M4B " {
            return "audio".into();
        }
        if brand == b"heic" || brand == b"heix" || brand == b"mif1" || brand == b"avif" {
            return "image".into();
        }
        return "video".into();
    }
    if size >= 0x8006 {
        if let Ok(mut f) = fs::File::open(path) {
            let mut sig = [0u8; 5];
            if f.seek(SeekFrom::Start(0x8001)).is_ok() && f.read_exact(&mut sig).is_ok() && &sig == b"CD001" {
                return "disc".into();
            }
        }
    }
    if std::str::from_utf8(head).is_ok() && head.iter().all(|&c| c >= 9) {
        return "document".into();
    }
    "unknown".into()
}

fn hidden(name: &str, _meta: &fs::Metadata) -> bool {
    if name.starts_with('$') || name.starts_with("~$") || name == "desktop.ini" || name == "thumbs.db"
        || name == "Thumbs.db"
    {
        return true;
    }
    #[cfg(windows)]
    {
        let attrs = _meta.file_attributes();
        if attrs != 0 {
            return attrs & (FILE_ATTRIBUTE_HIDDEN | FILE_ATTRIBUTE_SYSTEM) != 0;
        }
    }
    name.starts_with('.')
}

fn mtime(meta: &fs::Metadata) -> f64 {
    meta.modified()
        .ok()
        .and_then(|t| t.duration_since(UNIX_EPOCH).ok())
        .map(|d| d.as_secs_f64())
        .unwrap_or(0.0)
}

fn os_err(e: std::io::Error, path: &str) -> PyErr {
    // OSError(errno, texto, ruta, winerror): con winerror, Python elige la subclase igual que os.scandir
    // (FileNotFoundError, PermissionError, NotADirectoryError…).
    match e.raw_os_error() {
        Some(code) => PyOSError::new_err((0, e.to_string(), path.to_string(), code)),
        None => PyOSError::new_err((0, e.to_string(), path.to_string())),
    }
}

/// Contenido inmediato de `path` sin ocultos ni de sistema: [(nombre, es_carpeta, tamaño, mtime, categoría)].
#[pyfunction]
#[pyo3(signature = (path, sniff_unknown=true))]
fn scan_dir(
    py: Python<'_>,
    path: String,
    sniff_unknown: bool,
) -> PyResult<Vec<(String, bool, u64, f64, String)>> {
    let res = py.detach(|| -> Result<Vec<_>, std::io::Error> {
        let guard = TABLES.read().unwrap();
        let t = guard.as_ref().ok_or_else(|| std::io::Error::other("aero_core sin configurar"))?;
        let mut out = Vec::new();
        for entry in fs::read_dir(&path)? {
            let Ok(entry) = entry else { continue };
            let name = entry.file_name().to_string_lossy().into_owned();
            // En Windows los metadatos vienen de FindNextFile: sin llamadas extra al disco.
            let Ok(meta) = entry.metadata() else { continue };
            if hidden(&name, &meta) {
                continue;
            }
            let ft = meta.file_type();
            let is_dir = ft.is_dir();
            let size = if is_dir { 0 } else { meta.len() };
            let mut cat = by_extension(t, &name, is_dir);
            if cat == "unknown" && size > 0 && sniff_unknown {
                cat = sniff(t, &entry.path(), size);
            }
            out.push((name, is_dir, size, mtime(&meta), cat));
        }
        Ok(out)
    });
    res.map_err(|e| os_err(e, &path))
}

/// Recorre la carpeta con límites de elementos y tiempo, sin seguir enlaces:
/// (archivos inmediatos, carpetas inmediatas, tamaño total, completo).
#[pyfunction]
#[pyo3(signature = (path, max_items=200_000, max_seconds=4.0))]
fn folder_stats(py: Python<'_>, path: String, max_items: u64, max_seconds: f64) -> (u64, u64, u64, bool) {
    py.detach(|| {
        let end = Instant::now() + Duration::from_secs_f64(max_seconds.max(0.0));
        let root = PathBuf::from(&path);
        let mut stack = vec![root.clone()];
        let (mut files, mut dirs, mut size, mut n) = (0u64, 0u64, 0u64, 0u64);
        while let Some(d) = stack.pop() {
            let Ok(rd) = fs::read_dir(&d) else { continue };
            for entry in rd {
                n += 1;
                if n > max_items || (n % 512 == 0 && Instant::now() > end) {
                    return (files, dirs, size, false);
                }
                let Ok(entry) = entry else { continue };
                let Ok(ft) = entry.file_type() else { continue };
                if ft.is_symlink() {
                    continue;
                }
                if ft.is_dir() {
                    if d == root {
                        dirs += 1;
                    }
                    stack.push(entry.path());
                } else if ft.is_file() {
                    if let Ok(m) = entry.metadata() {
                        size += m.len();
                    }
                    if d == root {
                        files += 1;
                    }
                }
            }
        }
        (files, dirs, size, true)
    })
}

/// Igual que `command_palette.fold`: minúsculas y sin tildes (NFD sin marcas combinantes).
fn fold(s: &str) -> String {
    s.to_lowercase().nfd().filter(|c| !is_combining_mark(*c)).collect()
}

#[pyfunction]
fn fold_text(s: &str) -> String {
    fold(s)
}

/// Busca nombres que contengan todas las palabras, en el mismo orden que `os.walk` (arriba-abajo).
/// `stop` es un `threading.Event`: se consulta cada 256 entradas.
#[pyfunction]
#[pyo3(signature = (roots, query, stop=None, limit=400))]
fn search(
    py: Python<'_>,
    roots: Vec<String>,
    query: String,
    stop: Option<Py<PyAny>>,
    limit: usize,
) -> PyResult<Vec<String>> {
    let words: Vec<String> = fold(&query).split_whitespace().map(String::from).collect();
    let stopped = |py: Python<'_>| -> bool {
        match &stop {
            Some(ev) => ev.call_method0(py, "is_set").and_then(|v| v.extract::<bool>(py)).unwrap_or(false),
            None => false,
        }
    };
    let out = py.detach(|| {
        let mut out: Vec<String> = Vec::new();
        let mut count = 0usize;
        for root in &roots {
            // os.walk: se visita la carpeta, se listan sus archivos y carpetas y se baja en orden
            let mut todo: Vec<PathBuf> = vec![PathBuf::from(root)];
            while let Some(dir) = todo.pop() {
                let Ok(rd) = fs::read_dir(&dir) else { continue };
                let mut names_files = Vec::new();
                let mut names_dirs = Vec::new();
                for entry in rd.flatten() {
                    count += 1;
                    if count % 256 == 0 && Python::attach(|py| stopped(py)) {
                        return out;
                    }
                    let name = entry.file_name().to_string_lossy().into_owned();
                    let is_dir = entry.file_type().map(|t| t.is_dir()).unwrap_or(false);
                    if is_dir {
                        names_dirs.push(name);
                    } else {
                        names_files.push(name);
                    }
                }
                names_dirs.retain(|d| !d.starts_with('.') && d != "$RECYCLE.BIN" && d != "node_modules");
                let dir_str = dir.to_string_lossy().into_owned();
                for name in names_files.iter().chain(names_dirs.iter()) {
                    let f = fold(name);
                    if words.iter().all(|w| f.contains(w.as_str())) {
                        out.push(join(&dir_str, name));
                        if out.len() >= limit {
                            return out;
                        }
                    }
                }
                // la pila invierte: se apilan al revés para bajar en el orden del listado
                for d in names_dirs.iter().rev() {
                    todo.push(PathBuf::from(join(&dir_str, d)));
                }
            }
        }
        out
    });
    Ok(out)
}

/// os.path.join en Windows: añade «\» salvo que ya termine en separador.
fn join(dir: &str, name: &str) -> String {
    if dir.ends_with('\\') || dir.ends_with('/') {
        format!("{dir}{name}")
    } else {
        format!("{dir}\\{name}")
    }
}

#[pyfunction]
fn version() -> &'static str {
    env!("CARGO_PKG_VERSION")
}

#[pymodule]
fn aero_core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(configure, m)?)?;
    m.add_function(wrap_pyfunction!(scan_dir, m)?)?;
    m.add_function(wrap_pyfunction!(folder_stats, m)?)?;
    m.add_function(wrap_pyfunction!(search, m)?)?;
    m.add_function(wrap_pyfunction!(fold_text, m)?)?;
    m.add_function(wrap_pyfunction!(version, m)?)?;
    m.add_function(wrap_pyfunction!(tags::read_tags, m)?)?;
    m.add_function(wrap_pyfunction!(tags::read_tags_many, m)?)?;
    Ok(())
}

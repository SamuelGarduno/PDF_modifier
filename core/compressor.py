import os
import fitz
from typing import Tuple, Callable, Optional

def format_size(bytes_size:  int) -> str:
    for unit in ["B", "KB", "MB", "GB"]:
        if bytes_size < 1024.0:
            return f"{bytes_size:.2f} {unit}"
        bytes_size /= 1024.0
    return f"{bytes_size:.2f} TB"

def compress_pdf_file(
    input_path: str,
    output_path: str,
    progress_callback: Optional[Callable[[int], None]] = None
) -> Tuple[int, int, float]:
    
    initial_size = os.path.getsize(input_path)
    
    if progress_callback:
        progress_callback(10)
        
    doc = fitz.open(input_path)
    total_pages = len(doc)
    
    for i, page in enumerate(doc):
        if progress_callback:
            progress = 10 + int((i+1) / total_pages * 60)
            progress_callback(progress)
            
    if progress_callback:
        progress_callback(75)
        
    doc.save(
        output_path,
        garbage=4,
        deflate=True,
        clean=True
    )
    doc.close()
    
    if progress_callback:
        progress_callback(100)
        
    final_size = os.path.getsize(output_path)
    
    saving = max(0.0, ((initial_size - final_size) / initial_size) * 100.0)
    
    return initial_size, final_size, saving


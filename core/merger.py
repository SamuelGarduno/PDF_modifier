from pypdf import PdfWriter
from typing import List, Callable, Optional

def merge_pdf_files(
    file_paths: List[str],
    output_path: str,
    progress_callback: Optional[Callable[[int], None]] = None
) -> None:
    if len(file_paths) < 2:
        raise ValueError("Se requieren al menos 2 documentos para unir.")
    
    merger = PdfWriter()
    total_files = len(file_paths)
    
    for index, file_path in enumerate(file_paths, start=1):
        merger.append(file_path)
        if progress_callback:
            percent = int((index/total_files)*90)
            progress_callback(percent)
            
    merger.write(output_path)
    merger.close()
    
    if progress_callback:
        progress_callback(100)
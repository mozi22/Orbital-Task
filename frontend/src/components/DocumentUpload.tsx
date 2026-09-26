import { Loader2, Upload } from "lucide-react";
import { type DragEvent, useCallback, useRef, useState } from "react";
import { runWithConcurrency } from "../lib/concurrency";

// Batch uploads go through the existing single-file endpoint, one call per
// file, with at most this many in flight at once (limited concurrency, not
// fully serial and not all-at-once).
const MAX_CONCURRENT_UPLOADS = 3;

interface DocumentUploadProps {
	onUpload: (file: File) => void | Promise<void>;
	uploading?: boolean;
}

interface BatchProgress {
	completed: number;
	total: number;
}

function isPdf(file: File): boolean {
	return (
		file.type === "application/pdf" || file.name.toLowerCase().endsWith(".pdf")
	);
}

export function DocumentUpload({
	onUpload,
	uploading = false,
}: DocumentUploadProps) {
	const [dragOver, setDragOver] = useState(false);
	const [batchProgress, setBatchProgress] = useState<BatchProgress | null>(
		null,
	);
	const fileInputRef = useRef<HTMLInputElement>(null);

	const processFiles = useCallback(
		async (files: File[]) => {
			const pdfFiles = files.filter(isPdf);
			if (pdfFiles.length === 0) return;

			let completed = 0;
			setBatchProgress({ completed, total: pdfFiles.length });

			await runWithConcurrency(
				pdfFiles,
				MAX_CONCURRENT_UPLOADS,
				async (file) => {
					try {
						await onUpload(file);
					} finally {
						completed += 1;
						setBatchProgress({ completed, total: pdfFiles.length });
					}
				},
			);

			setBatchProgress(null);
		},
		[onUpload],
	);

	const handleDragOver = useCallback((e: DragEvent) => {
		e.preventDefault();
		setDragOver(true);
	}, []);

	const handleDragLeave = useCallback((e: DragEvent) => {
		e.preventDefault();
		setDragOver(false);
	}, []);

	const handleDrop = useCallback(
		(e: DragEvent) => {
			e.preventDefault();
			setDragOver(false);
			processFiles(Array.from(e.dataTransfer.files));
		},
		[processFiles],
	);

	const handleClick = useCallback(() => {
		fileInputRef.current?.click();
	}, []);

	const handleFileChange = useCallback(
		(e: React.ChangeEvent<HTMLInputElement>) => {
			processFiles(Array.from(e.target.files ?? []));
			if (fileInputRef.current) {
				fileInputRef.current.value = "";
			}
		},
		[processFiles],
	);

	const isBusy = uploading || batchProgress !== null;

	return (
		<button
			type="button"
			className={`w-full max-w-md cursor-pointer rounded-xl border-2 border-dashed px-8 py-10 text-center transition-colors ${
				dragOver
					? "border-neutral-400 bg-neutral-100"
					: "border-neutral-200 bg-white hover:border-neutral-300 hover:bg-neutral-50"
			}`}
			onDragOver={handleDragOver}
			onDragLeave={handleDragLeave}
			onDrop={handleDrop}
			onClick={handleClick}
		>
			<input
				ref={fileInputRef}
				type="file"
				accept=".pdf"
				multiple
				className="hidden"
				onChange={handleFileChange}
			/>

			{isBusy ? (
				<div className="flex flex-col items-center">
					<Loader2 className="mb-3 h-10 w-10 animate-spin text-neutral-400" />
					<p className="text-sm font-medium text-neutral-600">
						{batchProgress && batchProgress.total > 1
							? `Uploading document ${Math.min(
									batchProgress.completed + 1,
									batchProgress.total,
								)} of ${batchProgress.total}...`
							: "Uploading document..."}
					</p>
				</div>
			) : (
				<div className="flex flex-col items-center">
					<Upload className="mb-3 h-10 w-10 text-neutral-400" />
					<p className="text-sm font-medium text-neutral-600">
						Upload PDF documents
					</p>
					<p className="mt-1 text-xs text-neutral-400">
						Click or drag and drop one or more files
					</p>
				</div>
			)}
		</button>
	);
}

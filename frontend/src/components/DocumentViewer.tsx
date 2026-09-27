import * as CollapsiblePrimitive from "@radix-ui/react-collapsible";
import {
	ChevronDown,
	ChevronLeft,
	ChevronRight,
	FileText,
	Loader2,
	Pencil,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { Document as PDFDocument, Page, pdfjs } from "react-pdf";
import "react-pdf/dist/Page/AnnotationLayer.css";
import "react-pdf/dist/Page/TextLayer.css";
import { getDocumentUrl } from "../lib/api";
import type { Document } from "../types";
import { Button } from "./ui/button";

pdfjs.GlobalWorkerOptions.workerSrc = new URL(
	"pdfjs-dist/build/pdf.worker.min.mjs",
	import.meta.url,
).toString();

const MIN_WIDTH = 280;
const MAX_WIDTH = 700;
const DEFAULT_WIDTH = 400;

interface DocumentViewerProps {
	documents: Document[];
	/**
	 * Called when a section's pencil-edit rename form is submitted with a
	 * non-blank new name. Expected to call the PATCH /api/documents/{id}
	 * endpoint (via the useDocuments hook's `rename`) and resolve on
	 * success; rejecting keeps that section's inline editor open and
	 * surfaces the error message so the user can retry instead of silently
	 * losing their edit.
	 */
	onRename?: (documentId: string, displayName: string) => Promise<unknown>;
}

interface DocumentLabelProps {
	document: Document;
	onRename?: (documentId: string, displayName: string) => Promise<unknown>;
}

function DocumentLabel({ document, onRename }: DocumentLabelProps) {
	const [editing, setEditing] = useState(false);
	const [draftName, setDraftName] = useState(document.display_name);
	const [saving, setSaving] = useState(false);
	const [renameError, setRenameError] = useState<string | null>(null);
	const inputRef = useRef<HTMLInputElement>(null);

	// Focus the rename input the moment editing starts, without relying on
	// the (lint-disallowed) autoFocus attribute.
	useEffect(() => {
		if (editing) {
			inputRef.current?.focus();
		}
	}, [editing]);

	const startEditing = useCallback(
		(e: React.MouseEvent) => {
			// The pencil button sits inside the same header row as the
			// accordion's expand/collapse trigger; stop the click from
			// bubbling so opening the rename editor never also toggles the
			// section.
			e.stopPropagation();
			setDraftName(document.display_name);
			setRenameError(null);
			setEditing(true);
		},
		[document.display_name],
	);

	const cancelEditing = useCallback(() => {
		setEditing(false);
		setRenameError(null);
	}, []);

	const handleSubmit = useCallback(
		async (e: React.FormEvent) => {
			e.preventDefault();
			const trimmed = draftName.trim();
			if (!trimmed) {
				setRenameError("Name cannot be empty.");
				return;
			}
			if (!onRename) {
				setEditing(false);
				return;
			}
			try {
				setSaving(true);
				setRenameError(null);
				await onRename(document.id, trimmed);
				setEditing(false);
			} catch (err) {
				setRenameError(
					err instanceof Error ? err.message : "Failed to rename document",
				);
			} finally {
				setSaving(false);
			}
		},
		[draftName, document.id, onRename],
	);

	const handleKeyDown = useCallback(
		(e: React.KeyboardEvent<HTMLInputElement>) => {
			if (e.key === "Escape") {
				e.preventDefault();
				cancelEditing();
			}
		},
		[cancelEditing],
	);

	if (editing) {
		return (
			// biome-ignore lint/a11y/useKeyWithClickEvents: onClick here only stops a click inside the form from bubbling up to the accordion header's toggle trigger; it isn't a click-to-activate affordance needing a keyboard equivalent.
			<form
				onSubmit={handleSubmit}
				onClick={(e) => e.stopPropagation()}
				className="min-w-0 flex-1"
			>
				<input
					ref={inputRef}
					aria-label="Document name"
					value={draftName}
					disabled={saving}
					onChange={(e) => setDraftName(e.target.value)}
					onKeyDown={handleKeyDown}
					className="w-full rounded border border-neutral-300 px-1.5 py-0.5 text-sm font-medium text-neutral-800 focus:border-neutral-400 focus:outline-none"
				/>
				{renameError && (
					<p className="mt-1 text-xs text-red-600">{renameError}</p>
				)}
			</form>
		);
	}

	return (
		<div className="flex min-w-0 items-center gap-1.5">
			<p className="truncate text-sm font-medium text-neutral-800">
				{document.display_name}
			</p>
			<Button
				variant="ghost"
				size="icon"
				className="h-6 w-6 flex-shrink-0"
				aria-label="Rename document"
				onClick={startEditing}
			>
				<Pencil className="h-3.5 w-3.5 text-neutral-400" />
			</Button>
		</div>
	);
}

export function DocumentViewer({ documents, onRename }: DocumentViewerProps) {
	const [width, setWidth] = useState(DEFAULT_WIDTH);
	const [dragging, setDragging] = useState(false);
	// Which sections are currently expanded. A `Set` (rather than a single
	// id) intentionally allows more than one section open at once for now —
	// collapsing whichever section was previously open when a new one is
	// expanded is single-expand behavior, tracked separately (issue #26).
	// Unlimited simultaneous expansion is acceptable resource-wise here: the
	// document cap (5 documents, see upload widget) bounds the worst case to
	// 5 concurrently-mounted PDF viewers.
	const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());
	// Every section that has ever been expanded at least once. A section's
	// PDF state (numPages/currentPage/pdfLoading/pdfError, held inside
	// DocumentAccordionSection) must survive collapse/re-expand cycles, so
	// once a section has been opened we keep its content force-mounted
	// (hidden via CSS rather than unmounted) from then on. Sections that
	// have never been opened stay lazily unmounted, so collapsed documents
	// don't eagerly fetch PDFs no one has looked at yet.
	const [everExpandedIds, setEverExpandedIds] = useState<Set<string>>(
		new Set(),
	);
	const containerRef = useRef<HTMLDivElement>(null);

	const handleMouseDown = useCallback(
		(e: React.MouseEvent) => {
			e.preventDefault();
			setDragging(true);

			const startX = e.clientX;
			const startWidth = width;

			const handleMouseMove = (moveEvent: MouseEvent) => {
				const delta = startX - moveEvent.clientX;
				const newWidth = Math.min(
					MAX_WIDTH,
					Math.max(MIN_WIDTH, startWidth + delta),
				);
				setWidth(newWidth);
			};

			const handleMouseUp = () => {
				setDragging(false);
				window.removeEventListener("mousemove", handleMouseMove);
				window.removeEventListener("mouseup", handleMouseUp);
			};

			window.addEventListener("mousemove", handleMouseMove);
			window.addEventListener("mouseup", handleMouseUp);
		},
		[width],
	);

	const toggleSection = useCallback((documentId: string) => {
		setExpandedIds((prev) => {
			const next = new Set(prev);
			if (next.has(documentId)) {
				next.delete(documentId);
			} else {
				next.add(documentId);
				setEverExpandedIds((everPrev) => {
					if (everPrev.has(documentId)) return everPrev;
					const nextEver = new Set(everPrev);
					nextEver.add(documentId);
					return nextEver;
				});
			}
			return next;
		});
	}, []);

	const pdfPageWidth = width - 48; // account for px-4 padding on each side

	if (documents.length === 0) {
		return (
			<div
				style={{ width }}
				className="flex h-full flex-shrink-0 flex-col items-center justify-center border-l border-neutral-200 bg-neutral-50"
			>
				<FileText className="mb-3 h-10 w-10 text-neutral-300" />
				<p className="text-sm text-neutral-400">No document uploaded</p>
			</div>
		);
	}

	return (
		<div
			ref={containerRef}
			style={{ width }}
			className="relative flex h-full flex-shrink-0 flex-col overflow-y-auto border-l border-neutral-200 bg-white"
		>
			{/* Resize handle */}
			<div
				className={`absolute top-0 left-0 z-10 h-full w-1.5 cursor-col-resize transition-colors hover:bg-neutral-300 ${
					dragging ? "bg-neutral-400" : ""
				}`}
				onMouseDown={handleMouseDown}
			/>

			{documents.map((document) => (
				<DocumentAccordionSection
					key={document.id}
					document={document}
					expanded={expandedIds.has(document.id)}
					everExpanded={everExpandedIds.has(document.id)}
					onToggle={() => toggleSection(document.id)}
					pdfPageWidth={pdfPageWidth}
					onRename={onRename}
				/>
			))}
		</div>
	);
}

interface DocumentAccordionSectionProps {
	document: Document;
	expanded: boolean;
	everExpanded: boolean;
	onToggle: () => void;
	pdfPageWidth: number;
	onRename?: (documentId: string, displayName: string) => Promise<unknown>;
}

function DocumentAccordionSection({
	document,
	expanded,
	everExpanded,
	onToggle,
	pdfPageWidth,
	onRename,
}: DocumentAccordionSectionProps) {
	const [numPages, setNumPages] = useState<number>(0);
	const [currentPage, setCurrentPage] = useState(1);
	const [pdfLoading, setPdfLoading] = useState(true);
	const [pdfError, setPdfError] = useState<string | null>(null);

	const pdfUrl = getDocumentUrl(document.id);

	return (
		<CollapsiblePrimitive.Root
			open={expanded}
			onOpenChange={onToggle}
			className="border-b border-neutral-100"
		>
			{/*
			 * The rename label (with its own pencil button/inline-edit form)
			 * and the accordion's expand/collapse trigger are kept as
			 * siblings, not nested, so the pencil button is never an
			 * interactive element inside another interactive element:
			 * nesting a <button> (or the rename <input>) inside the trigger
			 * <button> would be invalid HTML, and a click on the pencil
			 * would bubble up and also toggle the section. The trigger's
			 * accessible name is set explicitly to the document's
			 * display_name (via aria-label) so it stays identifiable by name
			 * even though the visible display_name text now lives in the
			 * sibling DocumentLabel instead of inside the trigger itself.
			 */}
			<div className="flex items-center justify-between gap-2 px-4 py-3 hover:bg-neutral-50">
				<div className="min-w-0 flex-1">
					<DocumentLabel document={document} onRename={onRename} />
					<p className="text-xs text-neutral-400">
						{document.page_count} page
						{document.page_count !== 1 ? "s" : ""}
					</p>
				</div>
				<CollapsiblePrimitive.Trigger asChild>
					<button
						type="button"
						aria-label={document.display_name}
						className="flex-shrink-0 p-1"
					>
						<ChevronDown
							className={`h-4 w-4 text-neutral-400 transition-transform ${
								expanded ? "rotate-180" : ""
							}`}
						/>
					</button>
				</CollapsiblePrimitive.Trigger>
			</div>

			{/*
			 * Radix unmounts Collapsible.Content on collapse by default, which
			 * would discard the PDF/page state below (numPages/currentPage/
			 * pdfLoading/pdfError) and force a re-fetch + re-render from scratch
			 * on re-expand — while the page-nav UI would briefly show the stale
			 * currentPage/numPages from before ("Page 3 of 0"). Once a section
			 * has been opened at least once (`everExpanded`), we force-mount it
			 * from then on and hide it purely via CSS (`data-[state=closed]:
			 * hidden`) so re-expanding never re-fetches. Sections that have
			 * never been opened stay lazily unmounted so collapsed documents
			 * don't eagerly fetch PDFs no one has looked at.
			 */}
			<CollapsiblePrimitive.Content
				forceMount={everExpanded || undefined}
				className="data-[state=closed]:hidden"
			>
				<div className="flex flex-col">
					{/* PDF content */}
					<div className="flex-1 overflow-y-auto p-4">
						{pdfError && (
							<div className="rounded-lg bg-red-50 p-3 text-sm text-red-600">
								{pdfError}
							</div>
						)}

						<PDFDocument
							file={pdfUrl}
							onLoadSuccess={({ numPages: pages }) => {
								setNumPages(pages);
								setPdfLoading(false);
								setPdfError(null);
							}}
							onLoadError={(error) => {
								setPdfError(`Failed to load PDF: ${error.message}`);
								setPdfLoading(false);
							}}
							loading={
								<div className="flex items-center justify-center py-12">
									<Loader2 className="h-6 w-6 animate-spin text-neutral-400" />
								</div>
							}
						>
							{!pdfLoading && !pdfError && (
								<Page
									pageNumber={currentPage}
									width={pdfPageWidth}
									loading={
										<div className="flex items-center justify-center py-12">
											<Loader2 className="h-5 w-5 animate-spin text-neutral-300" />
										</div>
									}
								/>
							)}
						</PDFDocument>
					</div>

					{/* Page navigation */}
					{numPages > 0 && (
						<div className="flex items-center justify-center gap-3 border-t border-neutral-100 px-4 py-2.5">
							<Button
								variant="ghost"
								size="icon"
								className="h-7 w-7"
								aria-label="Previous page"
								disabled={currentPage <= 1}
								onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
							>
								<ChevronLeft className="h-4 w-4" />
							</Button>
							<span className="text-xs text-neutral-500">
								Page {currentPage} of {numPages}
							</span>
							<Button
								variant="ghost"
								size="icon"
								className="h-7 w-7"
								aria-label="Next page"
								disabled={currentPage >= numPages}
								onClick={() => setCurrentPage((p) => Math.min(numPages, p + 1))}
							>
								<ChevronRight className="h-4 w-4" />
							</Button>
						</div>
					)}
				</div>
			</CollapsiblePrimitive.Content>
		</CollapsiblePrimitive.Root>
	);
}

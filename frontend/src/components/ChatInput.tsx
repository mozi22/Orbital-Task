import { Paperclip, SendHorizontal } from "lucide-react";
import { type KeyboardEvent, useCallback, useRef, useState } from "react";
import { Button } from "./ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "./ui/tooltip";

interface ChatInputProps {
	onSend: (content: string) => void;
	onUpload: (file: File) => void | Promise<void>;
	onUploadSettled?: () => void;
	disabled: boolean;
	/** Number of documents currently attached to this conversation. */
	documentCount: number;
	/** The conversation-wide document cap (mirrors the backend's limit). */
	maxDocuments: number;
}

export function ChatInput({
	onSend,
	onUpload,
	onUploadSettled,
	disabled,
	documentCount,
	maxDocuments,
}: ChatInputProps) {
	const atCap = documentCount >= maxDocuments;
	const attachedLabel = `${documentCount}/${maxDocuments} documents attached`;
	const [value, setValue] = useState("");
	const textareaRef = useRef<HTMLTextAreaElement>(null);
	const fileInputRef = useRef<HTMLInputElement>(null);

	const handleSend = useCallback(() => {
		const trimmed = value.trim();
		if (!trimmed || disabled) return;
		onSend(trimmed);
		setValue("");
		if (textareaRef.current) {
			textareaRef.current.style.height = "auto";
		}
	}, [value, disabled, onSend]);

	const handleKeyDown = useCallback(
		(e: KeyboardEvent<HTMLTextAreaElement>) => {
			if (e.key === "Enter" && !e.shiftKey) {
				e.preventDefault();
				handleSend();
			}
		},
		[handleSend],
	);

	const handleInput = useCallback(() => {
		const textarea = textareaRef.current;
		if (!textarea) return;
		textarea.style.height = "auto";
		textarea.style.height = `${Math.min(textarea.scrollHeight, 200)}px`;
	}, []);

	const handleFileChange = useCallback(
		(e: React.ChangeEvent<HTMLInputElement>) => {
			const file = e.target.files?.[0];
			if (file) {
				// onUpload may reject on failure; the caller (App) is responsible
				// for surfacing that failure via visible error state, so it's
				// safe (and necessary, to avoid an unhandled rejection) to just
				// swallow the rejection here. onUploadSettled still fires either
				// way so the caller can reconcile state once the attempt is done.
				Promise.resolve(onUpload(file))
					.catch(() => {})
					.finally(() => onUploadSettled?.());
			}
			// Reset the input so the same file can be selected again
			if (fileInputRef.current) {
				fileInputRef.current.value = "";
			}
		},
		[onUpload, onUploadSettled],
	);

	return (
		<div className="border-t border-neutral-200 bg-white p-3">
			<div className="flex items-end gap-2 rounded-xl border border-neutral-200 bg-neutral-50 px-3 py-2">
				<Tooltip>
					<TooltipTrigger asChild>
						<div>
							<Button
								variant="ghost"
								size="icon"
								aria-label="Attach document"
								className="h-8 w-8 flex-shrink-0"
								disabled={atCap}
								onClick={() => fileInputRef.current?.click()}
							>
								<Paperclip className="h-4 w-4 text-neutral-500" />
							</Button>
						</div>
					</TooltipTrigger>
					<TooltipContent>{attachedLabel}</TooltipContent>
				</Tooltip>

				<input
					ref={fileInputRef}
					type="file"
					accept=".pdf"
					className="hidden"
					onChange={handleFileChange}
				/>

				<span className="flex-shrink-0 text-xs text-neutral-400">
					{attachedLabel}
				</span>

				<textarea
					ref={textareaRef}
					value={value}
					onChange={(e) => setValue(e.target.value)}
					onInput={handleInput}
					onKeyDown={handleKeyDown}
					placeholder="Ask a question about your document..."
					rows={1}
					className="max-h-[200px] min-h-[36px] flex-1 resize-none bg-transparent py-1.5 text-sm text-neutral-800 placeholder-neutral-400 outline-none"
					disabled={disabled}
				/>

				<Button
					variant="ghost"
					size="icon"
					className="h-8 w-8 flex-shrink-0"
					disabled={!value.trim() || disabled}
					onClick={handleSend}
				>
					<SendHorizontal
						className={`h-4 w-4 ${
							value.trim() && !disabled
								? "text-neutral-900"
								: "text-neutral-300"
						}`}
					/>
				</Button>
			</div>
		</div>
	);
}

import ReactMarkdown from "react-markdown";

interface Props {
  title: string;
  content: string;
}

export default function DocumentView({ title, content }: Props) {
  return (
    <div className="bg-ivory rounded-2xl shadow-[0_0_0_1px_var(--color-border-cream)]">
      <div className="border-b border-border-cream px-8 py-5">
        <h1 className="font-serif text-xl text-near-black">{title}</h1>
      </div>
      <div className="px-8 py-8 prose max-w-none">
        <ReactMarkdown>{content}</ReactMarkdown>
      </div>
    </div>
  );
}

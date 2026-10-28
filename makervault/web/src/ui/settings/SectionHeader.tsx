type Props = {
  title: string;
  subtitle: string;
  onBack: () => void;
};

export default function SectionHeader({ title, subtitle, onBack }: Props) {
  return (
    <div className="flex items-center justify-between">
      <div>
        <h2 className="text-xl font-semibold">{title}</h2>
        <p className="text-sm opacity-70">{subtitle}</p>
      </div>
      <button
        className="text-sm px-3 py-2 rounded-md border border-panel-strong"
        onClick={onBack}
      >
        Back
      </button>
    </div>
  );
}

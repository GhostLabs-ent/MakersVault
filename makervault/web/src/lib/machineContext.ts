import type { Machine, MachineCategory } from "./api";


export const DESCRIPTIVE_CONTEXT_NOTICE =
  "Descriptive context only. No job was sent." as const;

export const MACHINE_PERMANENT_CONFIRMATION =
  "PERMANENTLY DELETE MACHINE";

export const MACHINE_CATEGORIES: Array<{
  id: MachineCategory;
  label: string;
}> = [
  { id: "fdm_printer", label: "FDM printer" },
  { id: "resin_printer", label: "Resin printer" },
  { id: "laser", label: "Laser" },
  { id: "cnc", label: "CNC" },
  { id: "pcb", label: "PCB" },
  { id: "other", label: "Other" },
];

export function machineCategoryLabel(category: MachineCategory) {
  return MACHINE_CATEGORIES.find(option => option.id === category)?.label || category;
}

export function activePreparedTargets(machines: Machine[]) {
  return machines
    .filter(machine => (
      !machine.archived_at
      && (machine.category === "fdm_printer" || machine.category === "resin_printer")
    ))
    .sort((a, b) => a.name.localeCompare(b.name) || a.id.localeCompare(b.id));
}

export function shouldLoadMachineContext(detailOpen: boolean) {
  return detailOpen;
}

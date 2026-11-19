# Claude Island - a desktop widget for watching your Claude Code sessions
# Copyright (c) 2026 Mohamed HAMANA (github.com/MedRu). MIT License, see LICENSE.
# Selects the Windows Terminal tab whose title matches -Title and brings its window to the front.
# -Title is normalised like winctl.norm(): lower case, leading glyph removed. Called by winctl.focus().
param([Parameter(Mandatory = $true)][string]$Title)
Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes
$A = [System.Windows.Automation.AutomationElement]
$root = $A::RootElement
$winCond = New-Object System.Windows.Automation.PropertyCondition(
    $A::ClassNameProperty, "CASCADIA_HOSTING_WINDOW_CLASS")
$tabCond = New-Object System.Windows.Automation.PropertyCondition(
    $A::ControlTypeProperty, [System.Windows.Automation.ControlType]::TabItem)
foreach ($w in $root.FindAll([System.Windows.Automation.TreeScope]::Children, $winCond)) {
    foreach ($t in $w.FindAll([System.Windows.Automation.TreeScope]::Descendants, $tabCond)) {
        $n = ($t.Current.Name -replace '^[\W_]+', '').Trim().ToLower()
        if ($n -eq $Title -or ($n.Length -ge 12 -and ($n.StartsWith($Title) -or $Title.StartsWith($n)))) {
            $select = [System.Windows.Automation.SelectionItemPattern]::Pattern
            try { $t.GetCurrentPattern($select).Select() } catch {}
            try { $w.SetFocus() } catch {}
            exit 0
        }
    }
}
exit 1

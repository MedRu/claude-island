# Claude Island - a desktop widget for watching your Claude Code sessions
# Copyright (c) 2026 Mohamed HAMANA (github.com/MedRu). MIT License, see LICENSE.
# Prints "<window handle> <number of tabs>" for every Windows Terminal window.
# winctl.tab_counts() uses it so that windows with several tabs are never hidden or closed as a whole.
Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes
$A = [System.Windows.Automation.AutomationElement]
$winCond = New-Object System.Windows.Automation.PropertyCondition(
    $A::ClassNameProperty, "CASCADIA_HOSTING_WINDOW_CLASS")
$tabCond = New-Object System.Windows.Automation.PropertyCondition(
    $A::ControlTypeProperty, [System.Windows.Automation.ControlType]::TabItem)
foreach ($w in $A::RootElement.FindAll([System.Windows.Automation.TreeScope]::Children, $winCond)) {
    $n = $w.FindAll([System.Windows.Automation.TreeScope]::Descendants, $tabCond).Count
    "$($w.Current.NativeWindowHandle) $n"
}

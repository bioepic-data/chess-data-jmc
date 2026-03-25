#!/bin/bash

# Dataset mapping: doi|directory|package_id
datasets=(
    "doi:10.15485/3022242|leaf_area_index|ess-dive-6d3178c5222ea40-20260312T223819556"
    "doi:10.15485/3014404|vegetation_attributes_photos|ess-dive-c867baa5f602eed-20260310T172234320"
    "doi:10.15485/2404585|forest_structure_analysis|ess-dive-811ab9412c1fa65-20260309T160901401"
    "doi:10.15485/1618130|2018_field_sampling|ess-dive-1438b7d6eaa70e1-20260309T160550600"
    "doi:10.15485/1617203|lidar_elevation_data|ess-dive-8f5e3f64125141f-20260309T160525556"
    "doi:10.15485/1617204|hyperspectral_imaging_radiance|ess-dive-b84d23f79a033e0-20260309T160458524"
    "doi:10.15485/1617202|survey_report|ess-dive-19a8417a3dc75e2-20260309T160440744"
    "doi:10.15485/2403350|waveform_lidar_data|ess-dive-3b439ff48ee447d-20260309T160420948"
    "doi:10.15485/1618131|reflectance_mosaics_maps|ess-dive-f78cb03d11550da-20260309T160313214"
    "doi:10.15485/2587101|soil_metagenomes|ess-dive-67162e9ab90f7e7-20260309T160128985"
    "doi:10.15485/1602034|vegetation_classification_map|ess-dive-46699da2f774f20-20260309T160105337"
    "doi:10.15485/3013006|geophysical_survey|ess-dive-460e696d8210ed3-20260309T155937802"
    "doi:10.15485/2997555|vegetation_soil_spectra|ess-dive-c938a042bca2b42-20260309T155648105"
)

BASE_URL="https://data.ess-dive.lbl.gov/catalog/d1/mn/v2/object"
MAX_SIZE=$((1024 * 1024 * 1024))  # 1 GB in bytes

for dataset in "${datasets[@]}"; do
    IFS='|' read -r doi directory package_id <<< "$dataset"
    echo "============================================"
    echo "Processing: $doi"
    echo "Directory: $directory"
    echo "Package ID: $package_id"
    echo "============================================"
    
    # Initialize download log
    download_log="${directory}/DOWNLOAD_LOG.md"
    echo "# Download Log for ${doi}" > "$download_log"
    echo "" >> "$download_log"
    echo "Downloaded: $(date)" >> "$download_log"
    echo "" >> "$download_log"
    echo "## Files Downloaded" >> "$download_log"
    echo "" >> "$download_log"
    
    skipped_log=""
    
    # Download the resource map / EML to get list of data files
    resource_map="/tmp/${package_id}_resource.xml"
    wget -q -O "$resource_map" "${BASE_URL}/${package_id}" 2>&1
    
    if [ ! -s "$resource_map" ]; then
        echo "✗ Failed to download resource map" | tee -a "$download_log"
        continue
    fi
    
    # Extract data file identifiers (exclude the package_id itself)
    file_ids=$(grep -o 'ess-dive-[a-f0-9]*-[0-9T]*' "$resource_map" | sort -u | grep -v "$package_id")
    file_count=$(echo "$file_ids" | wc -l)
    
    echo "Found $file_count data files"
    echo ""
    
    # Download each data file
    count=0
    downloaded_count=0
    skipped_count=0
    
    for file_id in $file_ids; do
        count=$((count + 1))
        
        # Get file metadata to check size and filename
        meta_url="https://data.ess-dive.lbl.gov/catalog/d1/mn/v2/meta/${file_id}"
        wget -q -O "/tmp/${file_id}_meta.xml" "$meta_url"
        
        # Extract filename and size
        filename=$(grep -oP '<fileName>\K[^<]+' "/tmp/${file_id}_meta.xml" 2>/dev/null)
        filesize=$(grep -oP '<size>\K[^<]+' "/tmp/${file_id}_meta.xml" 2>/dev/null)
        
        if [ -z "$filename" ]; then
            filename="${file_id}"
        fi
        
        if [ -z "$filesize" ]; then
            filesize=0
        fi
        
        # Format file size for display
        if [ $filesize -ge $((1024*1024*1024)) ]; then
            size_display="$(echo "scale=2; $filesize/1024/1024/1024" | bc) GB"
        elif [ $filesize -ge $((1024*1024)) ]; then
            size_display="$(echo "scale=2; $filesize/1024/1024" | bc) MB"
        elif [ $filesize -ge 1024 ]; then
            size_display="$(echo "scale=2; $filesize/1024" | bc) KB"
        else
            size_display="${filesize} bytes"
        fi
        
        echo "[$count/$file_count] $filename ($size_display)"
        
        # Check if file exceeds 1 GB
        if [ $filesize -gt $MAX_SIZE ]; then
            echo "  ⚠ Skipping - file too large (>1GB)"
            # Create zero-length placeholder
            touch "${directory}/${filename}.placeholder"
            skipped_count=$((skipped_count + 1))
            skipped_log="${skipped_log}\n- **${filename}** (${size_display}) - File ID: ${file_id}"
        else
            # Download the file
            data_url="${BASE_URL}/${file_id}"
            wget -q -O "${directory}/${filename}" "$data_url"
            
            if [ $? -eq 0 ] && [ -s "${directory}/${filename}" ]; then
                echo "  ✓ Downloaded"
                downloaded_count=$((downloaded_count + 1))
                echo "- **${filename}** (${size_display}) - File ID: ${file_id}" >> "$download_log"
            else
                echo "  ✗ Failed"
                echo "- **${filename}** (${size_display}) - ⚠ DOWNLOAD FAILED" >> "$download_log"
            fi
        fi
        
        rm -f "/tmp/${file_id}_meta.xml"
    done
    
    # Append skipped files section if any
    if [ $skipped_count -gt 0 ]; then
        echo "" >> "$download_log"
        echo "## Files Skipped (>1GB)" >> "$download_log"
        echo "" >> "$download_log"
        echo "The following files were skipped due to size limits. Zero-length placeholder files were created with .placeholder extension:" >> "$download_log"
        echo "" >> "$download_log"
        echo -e "$skipped_log" >> "$download_log"
    fi
    
    echo "" >> "$download_log"
    echo "## Summary" >> "$download_log"
    echo "" >> "$download_log"
    echo "- Total files: $file_count" >> "$download_log"
    echo "- Downloaded: $downloaded_count" >> "$download_log"
    echo "- Skipped (>1GB): $skipped_count" >> "$download_log"
    
    echo ""
    echo "✓ Completed $directory ($downloaded_count downloaded, $skipped_count skipped)"
    echo "  See ${download_log} for details"
    echo ""
    rm -f "$resource_map"
done

echo "============================================"
echo "All downloads complete!"
echo "============================================"
